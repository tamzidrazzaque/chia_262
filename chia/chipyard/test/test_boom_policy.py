import shutil
import subprocess

import pytest

from chia.chipyard.boom_model import normalize_policy, policy_fragment, render_policy, validate_policy
from chia.chipyard.cost_model import verify_policy_defaults
from examples.boom_cost_model import pressure_proposals


def test_identity_policy_preserves_existing_snapshot_and_sources():
    identity = pressure_proposals.seed_profiles()[0]["policy"]
    assert normalize_policy(None) is None
    assert normalize_policy(identity) is None
    assert policy_fragment(identity) == ""


@pytest.mark.parametrize("change", [{"pressure_algorithm": True}, {"pressure_algorithm": 3},
    {"ira_loop_pressure": 1}, {"growth_budget": "arbitrary command"}, {"extra": 1}])
def test_policy_rejects_unbounded_or_wrong_types(change):
    policy = pressure_proposals.seed_profiles()[1]["policy"]
    with pytest.raises(ValueError):
        validate_policy({**policy, **change})


def test_policy_source_requires_the_pinned_option_hook():
    with pytest.raises(ValueError, match="source shape"):
        render_policy("a different backend", pressure_proposals.seed_profiles()[1]["policy"])


def test_real_cpp_guard_and_explicit_option_precedence(tmp_path):
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("C++ compiler unavailable")
    fragment = policy_fragment(pressure_proposals.seed_profiles()[3]["policy"])
    source = r'''
    #include <cassert>
    struct Options {
        int x_flag_sched_pressure, x_param_sched_pressure_algorithm;
        int x_flag_ira_loop_pressure, x_param_max_completely_peeled_insns;
        int x_param_unroll_jam_max_unroll;
    } global_options = {0, 1, 0, 200, 4}, global_options_set = {};
    struct Tune {} boom_tune_info, rocket_tune_info;
    const Tune *tune_param;
    #define SET_OPTION_IF_UNSET(opts, set, option, value) \
        do { if (!(set)->x_##option) (opts)->x_##option = value; } while (0)
    void apply() { FRAGMENT }
    int main() {
        // Explicit Rocket compilation keeps its defaults.
        tune_param = &rocket_tune_info;
        apply();
        assert(global_options.x_flag_sched_pressure == 0);
        assert(global_options.x_param_max_completely_peeled_insns == 200);
        // BOOM takes policy defaults, except options explicitly set by the user.
        tune_param = &boom_tune_info;
        apply();
        assert(global_options.x_flag_sched_pressure == 1);
        assert(global_options.x_param_max_completely_peeled_insns == 64);
        global_options = {0, 1, 0, 200, 4};
        global_options_set.x_flag_sched_pressure = 1;
        global_options_set.x_param_max_completely_peeled_insns = 1;
        global_options.x_param_max_completely_peeled_insns = 123;
        apply();
        assert(global_options.x_flag_sched_pressure == 0);
        assert(global_options.x_param_sched_pressure_algorithm == 2);
        assert(global_options.x_flag_ira_loop_pressure == 1);
        assert(global_options.x_param_max_completely_peeled_insns == 123);
        assert(global_options.x_param_unroll_jam_max_unroll == 1);
    }
    '''.replace("FRAGMENT", fragment)
    path = tmp_path / "policy.cc"
    path.write_text(source)
    subprocess.run([compiler, "-std=c++11", "-Wall", "-Werror", str(path), "-o", str(tmp_path / "check")], check=True)
    subprocess.run([str(tmp_path / "check")], check=True)


def test_factorial_profiles_freeze_costs_and_do_not_share_mutable_lists():
    profiles = pressure_proposals.seed_profiles()
    assert len({pressure_proposals.identity(p) for p in profiles}) == 4
    assert [p["policy"]["growth_budget"] for p in profiles] == ["default", "default", "compact", "compact"]
    for p in profiles:
        pressure_proposals.validate(p)
    profiles[0]["costs"]["fp_add"][0] = 999
    assert profiles[1]["costs"]["fp_add"][0] == 4
    with pytest.raises(ValueError):
        pressure_proposals.validate(profiles[0])


@pytest.mark.parametrize("broken", [None, "boom", "rocket", "explicit"])
def test_effective_compiler_options_are_verified_before_workload_build(monkeypatch, broken):
    def output(command, **kwargs):
        values = {"-fsched-pressure": "[disabled]", "-fira-loop-pressure": "[disabled]",
            "--param=sched-pressure-algorithm=<1,2>": "1", "--param=max-completely-peeled-insns=": "200",
            "--param=unroll-jam-max-unroll=": "4"}
        kind = "baseline"
        if command[0].startswith('/candidate'):
            if '-mtune=rocket' in command:
                kind = 'rocket'
            elif '-fno-sched-pressure' in command:
                kind = 'explicit'
                values.update({'--param=max-completely-peeled-insns=': '123', '--param=unroll-jam-max-unroll=': '3'})
            else:
                kind = 'boom'
                values.update({'-fsched-pressure': '[enabled]', '-fira-loop-pressure': '[enabled]',
                    '--param=sched-pressure-algorithm=<1,2>': '2', '--param=max-completely-peeled-insns=': '64',
                    '--param=unroll-jam-max-unroll=': '1'})
        if kind == broken:
            values['--param=max-completely-peeled-insns='] = '999'
        return '\n'.join(key + '\t' + value for key, value in reversed(list(values.items())))
    monkeypatch.setattr('chia.chipyard.cost_model.subprocess.check_output', output)
    policy = pressure_proposals.seed_profiles()[3]['policy']
    if broken:
        with pytest.raises(RuntimeError, match='effective BOOM policy'):
            verify_policy_defaults('/candidate', '/baseline', policy)
    else:
        assert verify_policy_defaults('/candidate', '/baseline', policy)['verified']
