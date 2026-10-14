"""The lab alias relay preserves stream data while restricting both endpoints."""

import asyncio
import socket
import json
from pathlib import Path
import subprocess
import sys
import time

import pytest

from examples.loopback_cluster import loopback_relay
from examples.loopback_cluster.loopback_relay import open_listeners, validate_mappings, verify_ready


def mapping(port, target=23456):
    return {"listen_host": "127.0.0.2", "listen_port": port,
            "target_host": "127.0.0.1", "target_port": target}


@pytest.mark.parametrize("change", [
    {"listen_host": "0.0.0.0"}, {"target_host": "192.0.2.1"},
    {"listen_port": 0}, {"target_port": True}, {"extra": 1},
])
def test_rejects_unsafe_mapping(change):
    with pytest.raises(ValueError):
        validate_mappings([mapping(12345) | change])


def test_rejects_duplicate_and_self_loop():
    with pytest.raises(ValueError):
        validate_mappings([mapping(12345), mapping(12345)])
    with pytest.raises(ValueError):
        validate_mappings([mapping(12345) | {"target_host": "127.0.0.2", "target_port": 12345}])


def test_bidirectional_stream_and_half_close():
    async def check():
        async def backend(reader, writer):
            data = await reader.read()
            writer.write(data[::-1])
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        target = await asyncio.start_server(backend, "127.0.0.1", 0)
        port = target.sockets[0].getsockname()[1]
        # The relay uses another loopback alias at the same port.
        relays = await open_listeners([mapping(port, port)])
        try:
            reader, writer = await asyncio.open_connection("127.0.0.2", port)
            payload = bytes(range(256)) * 4096
            writer.write(payload)
            await writer.drain()
            writer.write_eof()
            assert await asyncio.wait_for(reader.read(), 5) == payload[::-1]
            writer.close()
            await writer.wait_closed()
        finally:
            target.close()
            for server in relays:
                server.close()
            await asyncio.gather(target.wait_closed(), *(s.wait_closed() for s in relays))

    asyncio.run(check())


def test_occupied_port_preserves_existing_listener():
    async def check():
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.2", 0))
            occupied.listen()
            port = occupied.getsockname()[1]
            with pytest.raises(OSError):
                await open_listeners([mapping(port)])
            assert occupied.getsockname()[1] == port

    asyncio.run(check())


def test_readiness_checks_live_process_and_detects_changed_configuration(tmp_path):
    with socket.socket() as probe:
        probe.bind(("127.0.0.2", 0))
        port = probe.getsockname()[1]
    config, ready = tmp_path / "mappings.json", tmp_path / "ready.json"
    config.write_text(json.dumps([mapping(port)]))
    process = subprocess.Popen([sys.executable, str(Path(loopback_relay.__file__).resolve()),
                                "--config", str(config), "--ready", str(ready)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(.02)
        assert ready.exists()
        verify_ready(config, ready)
        config.write_text(json.dumps([mapping(port, target=23457)]))
        with pytest.raises(ValueError, match="does not match"):
            verify_ready(config, ready)
    finally:
        process.terminate()
        process.wait(timeout=5)
