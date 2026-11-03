import hashlib
import json
from pathlib import Path

import pytest

from chia.chipyard.boom_model import policy_fragment
from examples.boom_cost_model import focused_campaign as campaign, refinement_proposals, pressure_proposals


def archive(tmp_path, hardware=None):
    source = tmp_path / "archive"
    source.mkdir()
    proposal = refinement_proposals.seed_profiles()[0]
    best = {"index": 3, "success": True, "worker_index": 1, "proposal": proposal,
            "compiler": {"compiler_id": "b" * 64}}
    result = {"complete": True, "train_confirmation_checked": True,
              "confirmed_train_speedup": 1.02, "baseline_retained": False,
              "best_train_proposal": best, "history": [best]}
    path = source / "result.json"
    path.write_text(json.dumps(result))
    (source / "worker-1").mkdir()
    (source / "worker-1/hardware.json").write_text(json.dumps(hardware or {}))
    return {"incumbent_run": str(source), "incumbent_result_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "incumbent_compiler_id": "b" * 64, "campaign_kind": "pressure-refine",
            "benchmarks": ["648.exchange2_s"], "campaign_budget": 6, "confirm_repeats": 3,
            "confirmation_worker_index": 1, "min_improvement": 0.01, "min_incremental_improvement": 0.005,
            "final_ref": False}


def test_archive_is_confirmed_pinned_and_on_identical_hardware(tmp_path):
    config = archive(tmp_path, {"AGFI": "expected"})
    assert campaign.verify_incumbent_archive(config, {"AGFI": "expected"})["index"] == 3
    with pytest.raises(ValueError, match="hardware manifest"):
        campaign.verify_incumbent_archive(config, {"AGFI": "different"})
    path = Path(config["incumbent_run"]) / "result.json"
    path.write_text(path.read_text() + " ")
    with pytest.raises(ValueError, match="archive result changed"):
        campaign.verify_incumbent_archive(config, {"AGFI": "expected"})


def test_refinement_has_new_ablations_and_bounded_growth():
    seeds = refinement_proposals.seed_profiles()
    assert len({refinement_proposals.identity(p) for p in seeds}) == 6
    assert seeds[0]["policy"] == pressure_proposals.seed_profiles()[3]["policy"]
    assert seeds[1]["policy"]["ira_loop_pressure"] is False
    assert seeds[2]["policy"]["pressure_algorithm"] == 0
    for name, budget, jam in [('tight', 32, 1), ('relaxed', 128, 1), ('peel_only', 64, 4), ('jam_only', 200, 1)]:
        policy = {**seeds[0]["policy"], "growth_budget": name}
        text = policy_fragment(policy)
        assert f"param_max_completely_peeled_insns, {budget}" in text
        assert f"param_unroll_jam_max_unroll, {jam}" in text
    with pytest.raises(ValueError, match="outside this campaign"):
        pressure_proposals.validate(seeds[3])


def test_failed_confirmation_cannot_be_an_incumbent(tmp_path):
    config = archive(tmp_path)
    path = Path(config['incumbent_run']) / 'result.json'
    result = json.loads(path.read_text())
    result['confirmation_failed'] = True
    path.write_text(json.dumps(result))
    config['incumbent_result_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match='passed train confirmation'):
        campaign.verify_incumbent_archive(config, {})


def test_cache_import_is_limited_to_requested_anchor_phases(tmp_path):
    source = tmp_path / "cache"
    source.mkdir()
    for key, label in [('a' * 64, 'confirm-winner'), ('b' * 64, 'candidate-003-f2'), ('c' * 64, 'candidate-005-f2')]:
        (source / (key + '.json')).write_text(json.dumps({'key': key, 'source': '/private/' + label + '/train/job'}))
    destination = tmp_path / 'imported'
    campaign.import_baseline_cache(destination, [str(source)], ('confirm-winner', 'candidate-003-f2'))
    assert {p.stem for p in destination.iterdir()} == {'a' * 64, 'b' * 64}


def test_refinement_feedback_has_new_preset_values_and_incumbent_goal(tmp_path, monkeypatch):
    from types import SimpleNamespace
    captured = {}
    value = refinement_proposals.seed_profiles()[3]
    class LLM:
        def __init__(self, **kwargs):
            assert not kwargs['dangerously_skip_permissions']
        def prompt(self, prompt, tools):
            assert tools == []
            captured.update(json.loads(prompt))
            return SimpleNamespace(success=True, result=json.dumps(value))
    monkeypatch.setattr(pressure_proposals, 'ClaudeCodeLLM', LLM)
    result = refinement_proposals.feedback_proposal({'model': 'example', 'min_incremental_improvement': .005},
                                                    [], [], tmp_path)
    assert result['policy']['growth_budget'] == 'tight'
    assert captured['growth_presets']['tight'] == [32, 1]
    assert captured['growth_presets']['peel_only'] == [64, 4]
    assert captured['incremental_promotion_margin'] == .005


@pytest.mark.parametrize('outcome', ['no_gain', 'confirmed', 'failed_confirmation'])
def test_refinement_compares_against_incumbent_and_confirms_on_selected_worker(tmp_path, monkeypatch, outcome):
    config = archive(tmp_path)
    labels = []
    class Experiment:
        def __init__(self, cfg, directory):
            self.config, self.directory, self.hardware = cfg, directory, {}
    def prepare(cfg, directory, index=None, proposal=None):
        return {'index': index, 'proposal': proposal, 'compiler': {'compiler_id': 'b' * 64 if index == 0 else str(index)},
                'code_generation': {'benchmark': str(index)}, 'workload': None}
    def measure(ex, item, label, **kwargs):
        labels.append((label, ex.workers[0]['instance_id'], kwargs.get('repeats')))
        if item['index'] is None:
            seconds = 100
        elif item['index'] == 0:
            seconds = 98
        elif item['index'] == 4:
            seconds = 97.9 if outcome == 'no_gain' else 97
            if label == 'confirm-winner' and outcome == 'failed_confirmation':
                seconds = 97.9
        else:
            seconds = 99
        return {'times': {'648.exchange2_s': seconds}}
    monkeypatch.setattr(campaign, 'Experiment', Experiment)
    monkeypatch.setattr(campaign, 'prepare', prepare)
    monkeypatch.setattr(campaign, 'measure', measure)
    monkeypatch.setattr(campaign, 'verified_workers', lambda *args: [{'instance_id': 'a'}, {'instance_id': 'b'}])
    monkeypatch.setattr(campaign, 'prior_train_evidence', lambda *args: [])
    monkeypatch.setattr(campaign.signal, 'signal', lambda *args: None)
    root = tmp_path / 'run'
    campaign.run(config, root)
    result = json.loads((root / 'result.json').read_text())
    assert result['complete'] and not result['reference_checked']
    if outcome == 'no_gain':
        assert result['incumbent_retained'] and result['selected_train_proposal']['index'] == 0
        assert not any(label.startswith('confirm-') for label, _, _ in labels)
    else:
        confirmation = [sample for sample in labels if sample[0].startswith('confirm-')]
        assert {label for label, _, _ in confirmation} == {'confirm-baseline', 'confirm-incumbent', 'confirm-winner'}
        assert all(worker == 'b' and repeats == 3 for _, worker, repeats in confirmation)
        if outcome == 'confirmed':
            assert not result['incumbent_retained']
            assert result['confirmed_incremental_speedup'] > 1.005
        else:
            assert result['incumbent_retained'] and result['confirmation_failed']
            assert result['selected_train_proposal']['index'] == 0
