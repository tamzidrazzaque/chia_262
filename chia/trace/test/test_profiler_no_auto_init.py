"""Local profiling checks must not start Ray services implicitly."""

from unittest.mock import Mock

import ray

from chia.base.ChiaFunction import ChiaFunction
from chia.trace import profiler


def test_local_function_does_not_auto_start_ray(monkeypatch):
    monkeypatch.setattr(profiler, "_collector_override", None)
    monkeypatch.setattr(profiler, "_profiler", None)
    monkeypatch.setattr(ray, "is_initialized", lambda: False)
    lookup = Mock(side_effect=AssertionError("actor lookup would auto-start Ray"))
    monkeypatch.setattr(ray, "get_actor", lookup)

    @ChiaFunction()
    def local_work():
        return 42

    assert local_work() == 42
    assert profiler.get_profiler().enabled is False
    lookup.assert_not_called()


def test_initialized_cluster_still_finds_profile_collector(monkeypatch):
    monkeypatch.setattr(profiler, "_collector_override", None)
    monkeypatch.setattr(ray, "is_initialized", lambda: True)
    actor = object()
    lookup = Mock(return_value=actor)
    monkeypatch.setattr(ray, "get_actor", lookup)
    assert profiler.get_collector(namespace="setup-test") is actor
    lookup.assert_called_once_with("ChiaProfileCollector", namespace="setup-test")
