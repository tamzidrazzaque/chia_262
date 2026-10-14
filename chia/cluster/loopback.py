"""Fail-closed checks for a shared host's per-process listener policy.

The native guard configures the pinned Ray binaries without editing installed
packages or the host firewall. It is not a sandbox for arbitrary native code.
Launchers must load it before starting Python, and audit the resulting runtime.
"""

from __future__ import annotations

import ctypes
import errno
import ipaddress
import os
import socket


def require_guard() -> None:
    """Refuse startup unless the preload guard constrains actual Internet binds."""
    address = os.environ.get("CHIA_LOOPBACK_BIND_IP", "")
    try:
        if not ipaddress.IPv4Address(address).is_loopback:
            raise ValueError(address)
        ready = ctypes.CDLL(None).chia_loopback_guard_ready
        ready.restype = ctypes.c_int
        if ready() != 1:
            raise ValueError("guard not ready")
    except (AttributeError, ValueError) as exc:
        raise RuntimeError("The loopback bind guard must be loaded before Python starts") from exc
    with socket.socket() as listener:
        listener.bind(("0.0.0.0", 0))
        if listener.getsockname()[0] != address:
            raise RuntimeError("Wildcard bind escaped the loopback policy")
    with socket.socket() as listener:
        try:
            listener.bind(("192.0.2.1", 0))
        except OSError as exc:
            if exc.errno != errno.EACCES:
                raise RuntimeError("Non-loopback bind was not rejected by the guard") from exc
        else:
            raise RuntimeError("Non-loopback bind escaped the loopback policy")


def driver_options(address: str) -> dict:
    """Return Ray connection options consistent with an enabled bind policy.

    Args:
        address: The explicit GCS endpoint of the already running cluster.
    """
    options = {"address": address}
    if os.environ.get("CHIA_LOOPBACK_BIND_IP"):
        require_guard()
        # A driver's RPC address must agree with its constrained listener.
        # Ray's default network probing can otherwise advertise the LAN IP.
        options["_node_ip_address"] = os.environ["CHIA_LOOPBACK_BIND_IP"]
    return options


if __name__ == "__main__":
    require_guard()
    print("Loopback bind guard verified")
