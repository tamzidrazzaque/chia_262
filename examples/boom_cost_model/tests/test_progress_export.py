import json
from pathlib import Path

from examples.boom_cost_model.export_progress import trial


def test_trial_retains_policy_and_discards_private_generated_text():
    value = trial({'index': 3, 'success': True, 'proposal': {
        'costs': {'branch_cost': 4},
        'policy': {'pressure_algorithm': 2, 'ira_loop_pressure': True, 'growth_budget': 'unroll'},
        'rationale': 'PRIVATE_SENTINEL'},
        'compiler': {'compiler_id': 'a'*64, 'prefix': '/private/toolchain'},
        'failure': 'PRIVATE_SENTINEL', 'train_times': {'648.exchange2_s': 77.68}})
    assert value['policy']['growth_budget'] == 'unroll'
    assert 'PRIVATE_SENTINEL' not in json.dumps(value) and '/private' not in json.dumps(value)


def test_published_progress_distinguishes_train_reference_and_cached_samples():
    path = Path(__file__).parents[1]/'research/data/progress-20261103.json'
    d = json.loads(path.read_text())
    assert d['estimate'] and not d['SPEC_reportable_score']
    winner = next(c for c in d['campaigns'] if c['confirmed_train_speedup'] and c['confirmed_train_speedup'] > 1.05)
    assert winner['train_confirmation_checked']
    assert not winner['reference_checked']
    assert d['heldout_validation'][0]['excluded_from_proposals']
    assert any(s['reused'] for s in d['samples'])
    assert all(s['native_correctness_passed'] and s['simulation_completed'] for s in d['samples'])
    assert all('rationale' not in h for c in d['campaigns'] for h in c['history'])
    assert any(m.get('optimization_policy',{}).get('growth_budget') == 'unroll'
        and m.get('policy_options_verified',{}).get('verified')
        for m in d['compiler_models'].values() if m.get('optimization_policy'))
