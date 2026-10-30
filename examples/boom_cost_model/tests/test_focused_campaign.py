import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import threading

from examples.boom_cost_model import focused_campaign as campaign


def config():
    return {"benchmarks": ["648.exchange2_s"], "campaign_budget": 2, "confirm_repeats": 3,
            "min_improvement": 0.01, "final_ref": False, "baseline_cache_dirs": []}


def test_two_workers_use_their_own_baselines_and_drain(tmp_path, monkeypatch):
    workers = [{"instance_id": "first"}, {"instance_id": "second"}]
    class Experiment:
        def __init__(self, cfg, directory):
            self.config, self.directory, self.hardware = cfg, directory, {}
            directory.mkdir(parents=True, exist_ok=True)
    def prepare(cfg, directory, index=None, proposal=None):
        return {"index": index, "proposal": proposal, "compiler": {"compiler_id": str(index)},
                "code_generation": {"benchmark": str(index)}, "workload": None}
    def measure(ex, prepared, label, **kwargs):
        worker = ex.workers[0]["instance_id"]
        if prepared["index"] is None:
            time = 100 if worker == "first" else 110
        else:
            time = 80 if worker == "first" else 110
        return {"times": {"648.exchange2_s": time}}
    monkeypatch.setattr(campaign, "Experiment", Experiment)
    monkeypatch.setattr(campaign, "prepare", prepare)
    monkeypatch.setattr(campaign, "measure", measure)
    monkeypatch.setattr(campaign, "verified_workers", lambda *args: workers)
    monkeypatch.setattr(campaign, "prior_train_evidence", lambda *args: [])
    monkeypatch.setattr(campaign.signal, "signal", lambda *args: None)
    campaign.run(config(), tmp_path)
    result = json.loads((tmp_path / "result.json").read_text())
    history = {r["index"]: r for r in result["history"]}
    assert history[0]["instance_id"] == "first" and history[0]["speedup"] == 1.25
    assert history[1]["instance_id"] == "second" and history[1]["speedup"] == 1.0
    assert result["complete"] and not result["reference_checked"]


def test_executable_identity_requires_actual_binaries():
    a = {"spec17-train-aabb-648.exchange2_s": {"executables": {"program": "sha"}}}
    b = {"spec17-train-other-648.exchange2_s": {"executables": {"program": "sha"}}}
    assert campaign.code_identity(a) == campaign.code_identity(b)
    with pytest.raises(ValueError):
        campaign.code_identity({"job": {"executables": {}}})


@pytest.mark.parametrize("changes", [{"campaign_budget": 100}, {"confirm_repeats": 0},
                                    {"benchmarks": ["other"]}, {"train_timeout_seconds": True}])
def test_campaign_budgets_and_target_are_explicit(changes):
    with pytest.raises(ValueError):
        campaign.validate_config({**config(), **changes})


def test_baseline_cache_import_excludes_other_candidates(tmp_path):
    source = tmp_path / "cache"
    source.mkdir()
    for key, label in (("a" * 64, "baseline-f2"), ("b" * 64, "candidate-000-f2")):
        (source / (key + ".json")).write_text(json.dumps({"key": key, "source": f"/private/{label}/train/job"}))
    target = tmp_path / "imported"
    campaign.import_baseline_cache(target, [str(source)])
    assert [p.name for p in target.iterdir()] == ["a" * 64 + ".json"]


def test_stop_waits_for_current_sample_then_prevents_next_dispatch(tmp_path, monkeypatch):
    stop = threading.Event()
    calls = []
    def jobs(workload, directory, inputs, repeat, timings):
        calls.append(repeat)
        timings.setdefault("648.exchange2_s", []).append(1.0)
        stop.set()
    ex = SimpleNamespace(directory=tmp_path, workers=[{"ssh_alias": "owned-worker"}],
                         measure_jobs=jobs, config={"benchmarks": ["648.exchange2_s"]})
    monkeypatch.setattr(campaign.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=1))
    with pytest.raises(campaign.CampaignStopped):
        campaign.measure(ex, {"workload": None}, "confirm", repeats=3, stop=stop)
    assert calls == [0]
