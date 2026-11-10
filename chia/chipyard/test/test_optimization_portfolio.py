"""Guard the new interventions, including enum options and real C++ defaults."""

from copy import deepcopy
import shutil
import subprocess

import pytest

from chia.chipyard import boom_model, cost_model
from examples.boom_cost_model import autopilot, refinement_proposals


def anchor():
    value = refinement_proposals.seed_profiles()[0]
    value['policy'] = {'pressure_algorithm': 2, 'ira_loop_pressure': True,
                       'growth_budget': 'unroll'}
    return value


def test_isolated_seeds_preserve_costs_and_all_other_policy_fields():
    original = anchor()
    seeds = autopilot.optimization_seeds(original)
    assert len(seeds) == 5
    for seed in seeds:
        restored = deepcopy(seed)
        restored['policy']['growth_budget'] = 'unroll'
        restored['rationale'] = original['rationale']
        assert restored == original
        boom_model.validate_policy(seed['policy'])
    seeds[0]['costs']['int_mul'][0] = 999
    assert original['costs']['int_mul'][0] != 999
    assert seeds[1]['costs']['int_mul'][0] != 999


@pytest.mark.parametrize('suffix', list(boom_model.PORTFOLIO_DEFAULTS))
def test_real_cpp_option_defaults_are_boom_only_and_explicit_values_win(tmp_path, suffix):
    compiler = shutil.which('g++')
    if not compiler:
        pytest.skip('C++ compiler unavailable')
    policy = anchor()['policy']
    policy['growth_budget'] += '_' + suffix
    fragment = boom_model.policy_fragment(policy)
    settings = {'flag_sched_pressure': 1, 'param_sched_pressure_algorithm': 2,
                'flag_ira_loop_pressure': 1, 'param_max_completely_peeled_insns': 64,
                'param_unroll_jam_max_unroll': 1,
                **boom_model.EXTRA_POLICY_DEFAULTS[policy['growth_budget']]}
    declarations = '\n'.join('int x_'+key+';' for key in settings)
    checks = '\n'.join('assert(global_options.x_'+key+' == '+str(value)+');'
                       for key, value in settings.items())
    explicit = '\n'.join('global_options_set.x_'+key+' = 1; global_options.x_'+key+' = 7;'
                         for key in settings)
    unchanged = '\n'.join('assert(global_options.x_'+key+' == 7);' for key in settings)
    untouched = '\n'.join('assert(global_options.x_'+key+' == 0);' for key in settings)
    source = '''#include <cassert>
enum { IRA_REGION_ALL = 42 };
struct Options { DECLARATIONS } global_options = {}, global_options_set = {};
struct Tune {} boom_tune_info, rocket_tune_info;
const Tune *tune_param;
#define SET_OPTION_IF_UNSET(opts, set, option, value) \
    do { if (!(set)->x_##option) (opts)->x_##option = value; } while (0)
void apply() { FRAGMENT }
int main() {
    tune_param = &rocket_tune_info; apply(); UNTOUCHED
    tune_param = &boom_tune_info; apply(); CHECKS
    EXPLICIT
    apply(); UNCHANGED
}
'''
    for key, value in [('DECLARATIONS', declarations), ('FRAGMENT', fragment),
                       ('CHECKS', checks), ('EXPLICIT', explicit),
                       ('UNCHANGED', unchanged), ('UNTOUCHED', untouched)]:
        source = source.replace(key, value)
    path = tmp_path/'policy.cc'
    path.write_text(source)
    subprocess.run([compiler, '-std=c++11', '-Wall', '-Werror', str(path),
                    '-o', str(tmp_path/'check')], check=True)
    subprocess.run([str(tmp_path/'check')], check=True)


@pytest.mark.parametrize('broken', [None, 'boom', 'rocket', 'explicit'])
def test_option_verification_checks_enum_rocket_and_override(monkeypatch, broken):
    def output(command, **kwargs):
        values = {'-fsched-pressure': '[disabled]', '-fira-loop-pressure': '[disabled]',
            '--param=sched-pressure-algorithm=': '1', '--param=max-completely-peeled-insns=': '200',
            '--param=unroll-jam-max-unroll=': '4', '--param=max-inline-insns-auto=': '30',
            '--param=inline-unit-growth=': '40', '-funroll-loops': '[disabled]',
            '--param=max-unrolled-insns=': '256', '--param=max-average-unrolled-insns=': '128',
            '-flive-range-shrinkage': '[disabled]', '-fira-region=[one|all|mixed]': 'one'}
        kind = 'baseline'
        if command[0].startswith('/candidate'):
            kind = 'rocket' if '-mtune=rocket' in command else 'boom'
            if kind == 'boom':
                values.update({'-fsched-pressure': '[enabled]', '-fira-loop-pressure': '[enabled]',
                    '--param=sched-pressure-algorithm=': '2', '--param=max-completely-peeled-insns=': '64',
                    '--param=unroll-jam-max-unroll=': '1', '-funroll-loops': '[enabled]',
                    '-fira-region=[one|all|mixed]': 'all', '-flive-range-shrinkage': '[enabled]'})
            if '-fno-sched-pressure' in command:
                kind = 'explicit'
            for arg in command[1:]:
                if arg.startswith('--param='):
                    key, value = arg.rsplit('=', 1)
                    values[key+'='] = value
                elif arg.startswith('-fira-region='):
                    values['-fira-region=[one|all|mixed]'] = arg.split('=', 1)[1]
                elif arg.startswith('-fno-'):
                    values[arg.replace('-fno-', '-f', 1)] = '[disabled]'
                elif arg in values:
                    values[arg] = '[enabled]'
        if kind == broken:
            values['-fira-region=[one|all|mixed]'] = 'mixed'
        return '\n'.join(k+'\t'+v for k, v in values.items())
    monkeypatch.setattr(cost_model.subprocess, 'check_output', output)
    policy = anchor()['policy']
    policy['growth_budget'] = 'unroll_ira_all_shrink'
    if broken:
        with pytest.raises(RuntimeError, match='effective BOOM policy'):
            cost_model.verify_policy_defaults('/candidate', '/baseline', policy)
    else:
        assert cost_model.verify_policy_defaults('/candidate', '/baseline', policy)['verified']
