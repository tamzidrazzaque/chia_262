"""Native setup must not start Ray for an optional status display."""

from chia.firesim import manager_node


def test_local_manager_can_disable_ray_board(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("local manager attempted to start a Ray board")
    monkeypatch.setattr(manager_node, "watch", unexpected)
    node = manager_node.FireSimManagerNode(timeout_seconds=60, watch_status=False)
    assert node.timeout_seconds == 60


def test_existing_manager_keeps_status_board(monkeypatch):
    called = []
    monkeypatch.setattr(manager_node, "watch", called.append)
    manager_node.FireSimManagerNode()
    assert called == ["FPGA"]
