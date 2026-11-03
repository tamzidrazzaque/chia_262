import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from examples.boom_cost_model import focused_campaign as campaign, pressure_proposals, refinement_proposals
from examples.boom_cost_model.cost_refinement_proposals import CostRefinementProposals
from examples.boom_cost_model.tests.test_refinement_campaign import archive


def cost_config():
    return {"campaign_kind": "cost-refine", "anchor_proposal": refinement_proposals.seed_profiles()[0],
        "cost_axes": {"branch_cost": [4, 8], "memory_cost": [5, 7], "int_mul": [3, 4],
                      "gpr_load": [4, 8], "gpr_store": [4, 6]},
        "cost_seeds": [{"knobs": knobs, "rationale": "Test the specified cost interaction."} for knobs in
            [{}, {"memory_cost": 5}, {"gpr_load": 4, "gpr_store": 4}, {"branch_cost": 4},
             {"int_mul": 3}, {"memory_cost": 5, "gpr_load": 4, "gpr_store": 4, "branch_cost": 4}]]}


def test_seed_projection_and_incumbent_identity():
    config = cost_config()
    api = CostRefinementProposals(config)
    seeds = api.seed_profiles()
    assert len({api.identity(p) for p in seeds}) == 6
    assert api.identity(seeds[0]) == refinement_proposals.identity(config['anchor_proposal'])
    assert seeds[4]['costs']['int_mul'] == [3, 3]
    assert all(p['policy'] == config['anchor_proposal']['policy'] for p in seeds)
    seeds[0]['costs']['fp_add'][0] = 999
    assert api.seed_profiles()[0]['costs']['fp_add'] == [4, 4]


@pytest.mark.parametrize('change', ['policy', 'floating', 'cross_file', 'out_of_range', 'unequal_modes'])
def test_response_cannot_change_frozen_or_non_enumerated_values(change):
    api = CostRefinementProposals(cost_config())
    proposal = api.seed_profiles()[0]
    if change == 'policy': proposal['policy']['ira_loop_pressure'] = False
    if change == 'floating': proposal['costs']['fp_add'] = [3, 3]
    if change == 'cross_file': proposal['move_profile']['gpr_to_fpr'] = 1
    if change == 'out_of_range': proposal['costs']['memory_cost'] = 6
    if change == 'unequal_modes': proposal['costs']['int_mul'] = [3, 4]
    with pytest.raises(ValueError): api.validate(proposal)


@pytest.mark.parametrize('axis,values', [('fmv_cost', [1]), ('gpr_load', [64]), ('memory_cost', [True])])
def test_axis_definition_is_bounded(axis, values):
    config = cost_config()
    config['cost_axes'][axis] = values
    with pytest.raises(ValueError): CostRefinementProposals(config)


def test_feedback_is_data_only_and_can_change_costs_under_fixed_policy(tmp_path, monkeypatch):
    config = {**cost_config(), 'model': 'example', 'private_config_value': 'PRIVATE_SENTINEL'}
    api = CostRefinementProposals(config)
    proposal = api.seed_profiles()[1]
    captured = {}
    class LLM:
        def __init__(self, **kwargs):
            assert kwargs['extra_cli_args'] == ['--tools', '', '--strict-mcp-config']
            assert not kwargs['dangerously_skip_permissions']
        def prompt(self, prompt, tools):
            assert tools == [] and 'PRIVATE_SENTINEL' not in prompt
            captured.update(json.loads(prompt))
            return SimpleNamespace(success=True, result=json.dumps(proposal))
    monkeypatch.setattr(pressure_proposals, 'ClaudeCodeLLM', LLM)
    assert api.feedback_proposal(config, [{'pending': True}], [], tmp_path) == proposal
    assert captured['allowed_axes']['memory_cost'] == [5, 7]
    assert captured['history'][0]['pending']


def test_controller_ignores_out_of_domain_prior_profiles_and_confirms_cost_gain(tmp_path, monkeypatch):
    config = {**archive(tmp_path), **cost_config()}
    source = Path(config['incumbent_run']) / 'result.json'
    report = json.loads(source.read_text())
    report['history'].append({'index': 1, 'success': True, 'proposal': pressure_proposals.seed_profiles()[0]})
    source.write_text(json.dumps(report))
    config['incumbent_result_sha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
    class Experiment:
        def __init__(self, cfg, directory):
            self.config, self.directory, self.hardware = cfg, directory, {}
    def prepare(cfg, directory, index=None, proposal=None):
        return {'index': index, 'proposal': proposal, 'compiler': {'compiler_id': 'b' * 64 if index == 0 else str(index)},
                'code_generation': {'benchmark': str(index)}, 'workload': None}
    def measure(ex, item, label, **kwargs):
        return {'times': {'648.exchange2_s': 100 if item['index'] is None else 96 if item['index'] == 1 else 98}}
    monkeypatch.setattr(campaign, 'Experiment', Experiment)
    monkeypatch.setattr(campaign, 'prepare', prepare)
    monkeypatch.setattr(campaign, 'measure', measure)
    monkeypatch.setattr(campaign, 'verified_workers', lambda *args: [{'instance_id': 'a'}, {'instance_id': 'b'}])
    monkeypatch.setattr(campaign, 'prior_train_evidence', lambda *args: [])
    monkeypatch.setattr(campaign.signal, 'signal', lambda *args: None)
    root = tmp_path / 'run'
    campaign.run(config, root)
    result = json.loads((root / 'result.json').read_text())
    assert result['complete'] and not result['incumbent_retained']
    assert result['confirmed_incremental_speedup'] == 98 / 96


def test_supporting_control_archive_is_hash_pinned_and_same_compiler(tmp_path):
    config = archive(tmp_path)
    support = tmp_path / 'support'
    (support / 'worker-0').mkdir(parents=True)
    (support / 'worker-0/hardware.json').write_text('{}')
    selected = {'index': 0, 'worker_index': 0, 'success': True,
                'compiler': {'compiler_id': 'b' * 64}, 'proposal': refinement_proposals.seed_profiles()[0]}
    path = support / 'result.json'
    path.write_text(json.dumps({'complete': True, 'selected_train_proposal': selected, 'history': []}))
    config['incumbent_supporting_runs'] = [{'run_dir': str(support), 'result_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}]
    assert len(campaign.verify_incumbent_archive(config, {})['cache_archives']) == 2
    selected['compiler']['compiler_id'] = 'c' * 64
    path.write_text(json.dumps({'complete': True, 'selected_train_proposal': selected, 'history': []}))
    config['incumbent_supporting_runs'][0]['result_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match='selected another compiler'):
        campaign.verify_incumbent_archive(config, {})


@pytest.mark.parametrize('tamper', ['result', 'hardware'])
def test_supporting_archive_rejects_changed_evidence(tmp_path, tamper):
    config = archive(tmp_path)
    config['incumbent_supporting_runs'] = [{'run_dir': config['incumbent_run'],
                                          'result_sha256': config['incumbent_result_sha256']}]
    source = Path(config['incumbent_run'])
    if tamper == 'result':
        config['incumbent_supporting_runs'][0]['result_sha256'] = '0' * 64
    else:
        # Primary uses worker 1; supporting selection deliberately uses worker 0.
        report = json.loads((source / 'result.json').read_text())
        report['selected_train_proposal'] = {**report['best_train_proposal'], 'worker_index': 0}
        (source / 'result.json').write_text(json.dumps(report))
        config['incumbent_result_sha256'] = hashlib.sha256((source / 'result.json').read_bytes()).hexdigest()
        config['incumbent_supporting_runs'][0]['result_sha256'] = config['incumbent_result_sha256']
        (source / 'worker-0').mkdir()
        (source / 'worker-0/hardware.json').write_text('{"AGFI":"different"}')
    with pytest.raises(ValueError, match='supporting archive'):
        campaign.verify_incumbent_archive(config, {})
