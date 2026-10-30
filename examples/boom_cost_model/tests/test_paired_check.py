import pytest
import json
from types import SimpleNamespace

from examples.boom_cost_model import paired_check
from examples.boom_cost_model.paired_check import sample_plan, summarize


def test_counterbalanced_independent_positions():
    a, b = sample_plan(0), sample_plan(1)
    assert a == ["baseline", "candidate", "candidate", "baseline"]
    assert b == ["candidate", "baseline", "baseline", "candidate"]
    assert all(x != y for x, y in zip(a, b))
    with pytest.raises(ValueError):
        sample_plan(2)


def test_summary_uses_each_physical_workers_control():
    def samples(base, candidate):
        return [{"kind": kind, "times": {"benchmark": t}}
                for kind, t in zip(sample_plan(0), [base, candidate, candidate, base])]
    r = summarize({"a": samples(100, 80), "b": samples(110, 110)})
    assert r["a"]["speedup"] == 1.25
    assert r["b"]["speedup"] == 1.0
    with pytest.raises(ValueError):
        summarize({"incomplete": samples(100, 80)[:3]})


def test_dispatch_is_fresh_counterbalanced_and_uses_both_workers(tmp_path, monkeypatch):
    source, root = tmp_path / "source", tmp_path / "check"
    source.mkdir()
    root.mkdir()
    (source / "config.json").write_text(json.dumps({"benchmarks": ["benchmark"]}))
    candidate = {"index": 3, "success": True, "proposal": {}, "compiler": {"compiler_id": "candidate"}}
    (source / "result.json").write_text(json.dumps({"complete": True, "history": [candidate]}))
    workers = [{"instance_id": name, "ssh_alias": name} for name in ("first", "second")]
    calls = []
    class Experiment:
        def __init__(self, config, directory):
            self.directory, self.hardware = directory, {}
        def measure_jobs(self, workload, directory, inputs, repeat, timings):
            calls.append((self.workers[0]["instance_id"], repeat, workload))
            timings["benchmark"] = [100 if workload == "baseline" else 99]
    monkeypatch.setattr(paired_check, "Experiment", Experiment)
    monkeypatch.setattr(paired_check, "verified_workers", lambda *args: workers)
    monkeypatch.setattr(paired_check, "prepare", lambda cfg, dest, index=None, proposal=None:
        {"compiler": {"compiler_id": "baseline" if index is None else "candidate"},
         "workload": "baseline" if index is None else "candidate"})
    monkeypatch.setattr(paired_check.signal, "signal", lambda *args: None)
    monkeypatch.setattr(paired_check.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=1))
    paired_check.run(source, 3, root)
    result = json.loads((root / "result.json").read_text())
    assert result["complete"] and not result["reference_checked"]
    for index, worker in enumerate(workers):
        actual = [(slot, kind) for wid, slot, kind in calls if wid == worker["instance_id"]]
        assert actual == list(enumerate(sample_plan(index)))
    calls.clear()
    paired_check.run(source, 3, root)
    assert not calls  # A completed diagnostic is not silently rerun.


def test_cli_keeps_authenticated_loopback_driver_options(tmp_path, monkeypatch):
    monkeypatch.setattr(paired_check.sys, "argv", ["paired_check", "--source", str(tmp_path),
        "--candidate", "3", "--run-dir", str(tmp_path / "run")])
    monkeypatch.setenv("RAY_ADDRESS", "127.200.0.1:22379")
    monkeypatch.setattr(paired_check, "require_guard", lambda: None)
    monkeypatch.setattr(paired_check, "driver_options", lambda address: {"address": address, "guard": True})
    calls = []
    monkeypatch.setattr(paired_check.ray, "init", lambda **options: calls.append(options))
    monkeypatch.setattr(paired_check.ray, "shutdown", lambda: None)
    monkeypatch.setattr(paired_check, "run", lambda *args: None)
    paired_check.main()
    assert calls == [{"address": "127.200.0.1:22379", "guard": True}]
