"""Relay Chia's loopback aliases to SSH's localhost reverse forwards.

This user-owned process supports sshd GatewayPorts=no without changing SSH
policy. Every listener and backend is an IPv4 loopback address. Run it on F2
before establishing the reverse forwards; no host routing or firewall changes.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import ipaddress
import json
import os
import socket
from pathlib import Path


def validate_mappings(mappings: list[dict]) -> list[dict]:
    """Reject non-loopback endpoints, invalid ports and duplicate listeners."""
    if not mappings or len(mappings) > 256:
        raise ValueError("Expected between 1 and 256 loopback mappings")
    seen = set()
    for mapping in mappings:
        if set(mapping) != {"listen_host", "listen_port", "target_host", "target_port"}:
            raise ValueError("Unexpected mapping fields")
        for field in ("listen_host", "target_host"):
            if not ipaddress.IPv4Address(mapping[field]).is_loopback:
                raise ValueError("Both relay endpoints must be IPv4 loopback")
        for field in ("listen_port", "target_port"):
            if type(mapping[field]) is not int or not 1 <= mapping[field] <= 65535:
                raise ValueError("Invalid TCP port")
        address = (mapping["listen_host"], mapping["listen_port"])
        if address in seen or address == (mapping["target_host"], mapping["target_port"]):
            raise ValueError("Duplicate listener or self-loop")
        seen.add(address)
    return mappings


async def relay(reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                target_host: str, target_port: int) -> None:
    """Copy both streams with backpressure and preserve TCP half-closes."""
    backend = None
    try:
        upstream, backend = await asyncio.open_connection(target_host, target_port)

        async def pump(source, destination):
            while data := await source.read(65536):
                destination.write(data)
                await destination.drain()
            if destination.can_write_eof():
                destination.write_eof()
                await destination.drain()

        await asyncio.gather(pump(reader, backend), pump(upstream, writer))
    except (OSError, ConnectionError):
        pass
    finally:
        for stream in (writer, backend):
            if stream is not None:
                stream.close()
                try:
                    await stream.wait_closed()
                except (OSError, ConnectionError):
                    pass


async def open_listeners(mappings: list[dict]) -> list[asyncio.Server]:
    """Open all requested listeners or close this attempt's listeners on failure."""
    validate_mappings(mappings)
    servers = []
    slots = asyncio.Semaphore(256)

    def handler(mapping):
        async def connection(reader, writer):
            async with slots:
                await relay(reader, writer, mapping["target_host"], mapping["target_port"])
        return connection

    try:
        for mapping in mappings:
            servers.append(await asyncio.start_server(
                handler(mapping), mapping["listen_host"], mapping["listen_port"],
                backlog=16, limit=65536))
    except BaseException:
        for server in servers:
            server.close()
        await asyncio.gather(*(server.wait_closed() for server in servers))
        raise
    return servers


async def serve(config: Path, ready: Path) -> None:
    """Publish readiness only after every loopback listener has opened."""
    raw = config.read_bytes()
    servers = await open_listeners(json.loads(raw))
    ready.write_text(json.dumps({"pid": os.getpid(), "uid": os.getuid(),
        "config_sha256": hashlib.sha256(raw).hexdigest(),
        "listeners": [list(socket.getsockname()) for server in servers for socket in server.sockets],
    }, indent=2) + "\n")
    try:
        await asyncio.Future()
    finally:
        for server in servers:
            server.close()
        await asyncio.gather(*(server.wait_closed() for server in servers))
        if ready.exists() and json.loads(ready.read_text()).get("pid") == os.getpid():
            ready.unlink()


def verify_ready(config: Path, ready: Path) -> None:
    """Verify the owned process, exact mapping set and actual live listeners."""
    raw = config.read_bytes()
    mappings = validate_mappings(json.loads(raw))
    state = json.loads(ready.read_text())
    pid = state["pid"]
    if type(pid) is not int or pid <= 1:
        raise ValueError("Invalid relay PID")
    process = Path("/proc") / str(pid)
    if (config.stat().st_uid != os.getuid() or ready.stat().st_uid != os.getuid()
            or process.stat().st_uid != os.getuid() or state["uid"] != os.getuid()):
        raise ValueError("Relay must belong to the current user")
    arguments = process.joinpath("cmdline").read_bytes().split(b"\0")
    if (os.fsencode(Path(__file__).resolve()) not in arguments
            or os.fsencode(config.resolve()) not in arguments
            or os.fsencode(ready.resolve()) not in arguments):
        raise ValueError("PID does not identify this relay/configuration")
    expected = {(m["listen_host"], m["listen_port"]) for m in mappings}
    if (state["config_sha256"] != hashlib.sha256(raw).hexdigest()
            or {tuple(address) for address in state["listeners"]} != expected):
        raise ValueError("Relay readiness does not match configuration")
    for address in expected:
        with socket.create_connection(address, timeout=1):
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--ready", type=Path, required=True)
    parser.add_argument("--check", action="store_true", help="Verify an already running owned relay")
    args = parser.parse_args()
    if args.check:
        verify_ready(args.config, args.ready)
    else:
        asyncio.run(serve(args.config, args.ready))


if __name__ == "__main__":
    main()
