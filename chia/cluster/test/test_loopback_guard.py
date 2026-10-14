"""Exercise the actual native listener policy in child processes."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.fixture(scope="module")
def guard(tmp_path_factory):
    output = tmp_path_factory.mktemp("bind-guard") / "guard.so"
    source = Path(__file__).resolve().parents[3] / "examples/loopback_cluster/loopback_bind.c"
    subprocess.run(["gcc", "-shared", "-fPIC", "-Wall", "-Wextra", "-Werror",
                    "-o", str(output), str(source), "-ldl", "-pthread"], check=True)
    return output


def child(guard, code, **policy):
    env = {**os.environ, "LD_PRELOAD": str(guard),
           "CHIA_LOOPBACK_BIND_IP": "127.200.0.1"}
    env.pop("CHIA_LOOPBACK_PORT_MIN", None)
    env.pop("CHIA_LOOPBACK_PORT_MAX", None)
    env.update(policy)
    return subprocess.run([sys.executable, "-c", code], env=env,
                          capture_output=True, text=True, timeout=15)


@pytest.mark.parametrize("family,host,expected", [
    ("AF_INET", "0.0.0.0", "127.200.0.1"),
    ("AF_INET", "127.0.0.2", "127.0.0.2"),
    ("AF_INET6", "::", "::ffff:127.200.0.1"),
    ("AF_INET6", "::1", "::1"),
])
def test_wildcard_and_explicit_loopback(guard, family, host, expected):
    result = child(guard, f"import socket; s=socket.socket(socket.{family}); "
                   f"s.bind(({host!r},0)); print(s.getsockname()[0])")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected


@pytest.mark.parametrize("family,host", [
    ("AF_INET", "192.0.2.1"), ("AF_INET6", "2001:db8::1"),
    ("AF_INET6", "::ffff:192.0.2.1"),
])
def test_non_loopback_denied(guard, family, host):
    result = child(guard, f"import socket; s=socket.socket(socket.{family}); "
                   f"s.bind(({host!r},0))")
    assert result.returncode != 0
    assert "Permission denied" in result.stderr


@pytest.mark.parametrize("ip", ["", "192.0.2.1", "invalid"])
def test_invalid_policy_fails_closed(guard, ip):
    result = child(guard, "import socket; socket.socket().bind(('0.0.0.0',0))",
                   CHIA_LOOPBACK_BIND_IP=ip)
    assert result.returncode != 0
    assert "Permission denied" in result.stderr


def test_ephemeral_ports_are_bounded_and_exhaustion_fails(guard):
    result = child(guard, """
import errno, json, socket
sockets = []
for _ in range(2):
    s = socket.socket(); s.bind(('127.201.0.1',0)); sockets.append(s)
print(json.dumps([s.getsockname()[1] for s in sockets]))
try:
    socket.socket().bind(('127.201.0.1',0))
except OSError as exc:
    assert exc.errno == errno.EADDRINUSE
else:
    raise AssertionError('escaped the bounded port range')
""", CHIA_LOOPBACK_PORT_MIN="24997", CHIA_LOOPBACK_PORT_MAX="24998")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [24997, 24998]


def test_launcher_verifies_actual_preload(guard):
    result = child(guard, "from chia.cluster.loopback import require_guard; require_guard()")
    assert result.returncode == 0, result.stderr
    env = dict(os.environ)
    env.pop("LD_PRELOAD", None)
    result = subprocess.run([sys.executable, "-m", "chia.cluster.loopback"],
                            env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert "loaded before Python starts" in result.stderr


def test_driver_advertises_the_constrained_listener(guard):
    result = child(guard, "import json; from chia.cluster.loopback import driver_options; "
                   "print(json.dumps(driver_options('127.200.0.1:22379')))")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"address": "127.200.0.1:22379",
                                        "_node_ip_address": "127.200.0.1"}


def test_unconfigured_driver_keeps_existing_behavior(monkeypatch):
    from chia.cluster.loopback import driver_options
    monkeypatch.delenv("CHIA_LOOPBACK_BIND_IP", raising=False)
    assert driver_options("192.0.2.1:6379") == {"address": "192.0.2.1:6379"}
