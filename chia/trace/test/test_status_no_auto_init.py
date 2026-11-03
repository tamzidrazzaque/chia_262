"""Local FireSim setup must not start Ray merely to report optional status."""

from chia.trace import status


def test_uninitialized_status_does_not_resolve_actor(monkeypatch):
    monkeypatch.setattr(status.ray, "is_initialized", lambda: False)
    def unexpected(*args, **kwargs):
        raise AssertionError("status reporting attempted to resolve/start Ray")
    monkeypatch.setattr(status.ray, "get_actor", unexpected)
    status.report("FPGA", "worker", state="preparing")
