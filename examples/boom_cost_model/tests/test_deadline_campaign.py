from copy import deepcopy
import shutil
import subprocess

import pytest

from chia.chipyard import boom_model, cost_model
from examples.boom_cost_model import autopilot, focused_campaign, pressure_proposals
from examples.boom_cost_model.tests.test_autopilot import source


@pytest.mark.parametrize('preset',['inline','unroll','inline_unroll'])
def test_new_codegen_presets_respect_rocket_and_explicit_options(tmp_path,preset):
    compiler = shutil.which('g++')
    if compiler is None:
        pytest.skip('host C++ compiler unavailable')
    defaults = {'flag_sched_pressure':0,'param_sched_pressure_algorithm':1,'flag_ira_loop_pressure':0,
        'param_max_completely_peeled_insns':200,'param_unroll_jam_max_unroll':4,
        'param_max_inline_insns_auto':30,'param_inline_unit_growth':40,'flag_unroll_loops':0,
        'param_max_unrolled_insns':200,'param_max_average_unrolled_insns':80}
    policy = {**pressure_proposals.seed_profiles()[3]['policy'],'growth_budget':preset}
    expected = {**defaults,'flag_sched_pressure':1,'param_sched_pressure_algorithm':2,
        'flag_ira_loop_pressure':1,'param_max_completely_peeled_insns':64,'param_unroll_jam_max_unroll':1,
        **boom_model.EXTRA_POLICY_DEFAULTS[preset]}
    fields = ','.join('x_'+name for name in defaults)
    values = ','.join(str(v) for v in defaults.values())
    code = '#include <cassert>\nstruct Options {int '+fields+';};\n'
    code += 'Options global_options={'+values+'},global_options_set={};\n'
    code += 'struct Tune{} boom_tune_info,rocket; const Tune *tune_param;\n'
    code += '#define SET_OPTION_IF_UNSET(o,s,k,v) do{if(!(s)->x_##k)(o)->x_##k=v;}while(0)\n'
    code += 'void apply(){'+boom_model.policy_fragment(policy)+'}\nint main(){tune_param=&rocket;apply();\n'
    code += ''.join(f'assert(global_options.x_{k}=={v});\n' for k,v in defaults.items())
    code += 'tune_param=&boom_tune_info;apply();\n'
    code += ''.join(f'assert(global_options.x_{k}=={v});\n' for k,v in expected.items())
    code += ''.join(f'global_options.x_{k}=0;global_options_set.x_{k}=1;\n' for k in defaults)
    code += 'apply();\n'+''.join(f'assert(global_options.x_{k}==0);\n' for k in defaults)+'}\n'
    path = tmp_path/'policy.cc'
    path.write_text(code)
    subprocess.run([compiler,'-std=c++11','-Werror',str(path),'-o',str(tmp_path/'check')],check=True)
    subprocess.run([str(tmp_path/'check')],check=True)


@pytest.mark.parametrize('broken',[None,'boom','rocket','explicit'])
def test_extended_effective_option_queries_check_all_new_defaults(monkeypatch,broken):
    params = {'--param=max-inline-insns-auto':'30','--param=inline-unit-growth':'40',
        '-funroll-loops':'[disabled]','--param=max-unrolled-insns':'200','--param=max-average-unrolled-insns':'80'}
    def output(command,**kwargs):
        values = {'-fsched-pressure':'[disabled]','-fira-loop-pressure':'[disabled]',
            '--param=sched-pressure-algorithm':'1','--param=max-completely-peeled-insns':'200',
            '--param=unroll-jam-max-unroll':'4',**params}
        kind = 'baseline'
        if command[0].startswith('/candidate'):
            kind = 'rocket' if '-mtune=rocket' in command else 'explicit' if '-fno-sched-pressure' in command else 'boom'
            if kind == 'boom':
                values.update({'-fsched-pressure':'[enabled]','-fira-loop-pressure':'[enabled]',
                    '--param=sched-pressure-algorithm':'2','--param=max-completely-peeled-insns':'64',
                    '--param=unroll-jam-max-unroll':'1','--param=max-inline-insns-auto':'180',
                    '--param=inline-unit-growth':'80','-funroll-loops':'[enabled]',
                    '--param=max-unrolled-insns':'256','--param=max-average-unrolled-insns':'128'})
            elif kind == 'explicit':
                for option in list(values):
                    override = next((s for s in command if s.startswith(option+'=')),None)
                    if override: values[option] = override.split('=',2)[-1]
        if kind == broken: values['--param=max-inline-insns-auto'] = '999'
        return '\n'.join(k+('=' if k.startswith('--param') else '')+'\t'+v for k,v in values.items())
    monkeypatch.setattr(cost_model.subprocess,'check_output',output)
    policy = {**pressure_proposals.seed_profiles()[3]['policy'],'growth_budget':'inline_unroll'}
    if broken:
        with pytest.raises(RuntimeError,match='effective BOOM policy'):
            cost_model.verify_policy_defaults('/candidate','/baseline',policy)
    else:
        assert cost_model.verify_policy_defaults('/candidate','/baseline',policy)['verified']


def test_deadline_codegen_uses_structured_factorial_without_pointless_feedback(tmp_path,monkeypatch):
    directory = source(tmp_path)
    review = autopilot.review(directory)
    monkeypatch.setattr(autopilot.pressure_proposals,'request_json',lambda *_:pytest.fail('factorial requires no model call'))
    cfg = autopilot.plan(autopilot.read(directory/'config.json'),[review],tmp_path/'next',{'deadline_mode':True})
    assert cfg['benchmarks'] == ['648.exchange2_s']
    assert cfg['campaign_budget'] == cfg['prepare_seed_count'] == 4
    assert [p['policy']['growth_budget'] for p in cfg['adaptive_seeds']] == ['compact','inline','unroll','inline_unroll']
    assert all(p['costs'] == cfg['anchor_proposal']['costs'] for p in cfg['adaptive_seeds'])


def test_reference_milestones_limit_wall_time_without_using_reference_scores(tmp_path):
    directory = source(tmp_path)
    review = autopilot.review(directory)
    root = tmp_path/'reference'
    settings = {'reference_policy':'milestone','reference_min_speedup':1.05,'reference_interval_hours':24}
    assert autopilot.reference_due(review,root,settings)
    old = root/'old/result.json'
    autopilot.write(old,{'complete':True,'reference_speedup':.9})
    later = old.stat().st_mtime+25*3600
    assert not autopilot.reference_due(review,root,settings,now=later)
    review['confirmed_train_speedup'] = 1.06
    assert not autopilot.reference_due(review,root,settings,now=later-24*3600)
    assert autopilot.reference_due(review,root,settings,now=later)


@pytest.mark.parametrize('value',[0,9,True])
def test_preparation_count_is_bounded(tmp_path,value):
    directory = source(tmp_path)
    cfg = autopilot.read(directory/'config.json')
    cfg['confirmation_worker_index'] = 1
    cfg['prepare_seed_count'] = value
    with pytest.raises(ValueError,match='prepare_seed_count'):
        focused_campaign.validate_config(cfg)


@pytest.mark.parametrize('target,requested,expected',[
    ('648.exchange2_s',5400,86400),('641.leela_s',5400,86400),
    ('602.gcc_s',5400,86400),('641.leela_s',200000,200000)])
def test_train_timeout_covers_measured_longer_workloads(target,requested,expected):
    assert autopilot.train_timeout(target,requested) == expected


@pytest.mark.parametrize('target,requested',[('unknown',5400),('641.leela_s',True),('641.leela_s',-1)])
def test_train_timeout_rejects_bad_settings(target,requested):
    with pytest.raises(ValueError): autopilot.train_timeout(target,requested)
