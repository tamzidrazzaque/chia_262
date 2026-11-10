from copy import deepcopy
import fcntl
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from examples.boom_cost_model import autopilot, focused_campaign, refinement_proposals, reference_check
from examples.boom_cost_model.adaptive_proposals import AdaptiveProposals


def config():
    anchor = refinement_proposals.seed_profiles()[0]
    alternative = deepcopy(anchor)
    alternative['costs']['branch_cost'] = 4
    return {'campaign_kind':'adaptive', 'anchor_proposal':anchor,
        'cost_axes':{'branch_cost':[2,3,4,8,12]}, 'policy_axes':{'growth_budget':['default','compact','relaxed']},
        'adaptive_seeds':[anchor,alternative], 'benchmarks':['641.leela_s'], 'campaign_budget':6,
        'confirm_repeats':3, 'min_improvement':.01, 'final_ref':False,
        'model':'test', 'baseline_cache_dirs':[], 'fpga_workers':[]}


def test_cache_probe_waits_for_preparation_without_blocking_experiments(tmp_path):
    spec = {'config': str(tmp_path/'config.json'), 'prepared_directory': str(tmp_path/'prepared'),
            'result_directory': str(tmp_path/'results')}
    settings = {'cache_probe': spec}
    assert autopilot.pending_cache_probe(settings) is None
    autopilot.write(tmp_path/'prepared/correctness.json', {'success': True})
    autopilot.write(tmp_path/'prepared/build.json', {'suite': 'cache'})
    assert autopilot.pending_cache_probe(settings) == spec
    autopilot.write(tmp_path/'results/result.json', {'success': True})
    assert autopilot.pending_cache_probe(settings) is None
    autopilot.write(tmp_path/'results/result.json', {'success': False})
    with pytest.raises(RuntimeError, match='inspect'):
        autopilot.pending_cache_probe(settings)


def test_cache_probe_cannot_substitute_another_suite(tmp_path):
    spec = {'config': 'config.json', 'prepared_directory': str(tmp_path/'prepared'),
            'result_directory': str(tmp_path/'results')}
    autopilot.write(tmp_path/'prepared/correctness.json', {'success': True})
    autopilot.write(tmp_path/'prepared/build.json', {'suite': 'latency'})
    with pytest.raises(ValueError, match='cache suite'):
        autopilot.pending_cache_probe({'cache_probe': spec})


def test_optional_cache_failure_is_rejected_and_quarantined_once(tmp_path):
    spec = {'config': 'config.json', 'prepared_directory': str(tmp_path/'prepared'),
            'result_directory': str(tmp_path/'results'), 'failure_policy':'quarantine'}
    assert not autopilot.check_cache_probe_completion(spec, RuntimeError('guest timer too short'))
    report = json.loads((tmp_path/'results/quarantined.json').read_text())
    assert report['success'] is False and report['accepted_hardware_score'] is False
    assert autopilot.pending_cache_probe({'cache_probe':spec}) is None
    assert not (tmp_path/'results/result.json').exists()
    with pytest.raises(RuntimeError, match='quarantined'):
        autopilot.pending_cache_probe({'cache_probe':{k:v for k,v in spec.items() if k!='failure_policy'}})


def test_default_cache_failure_still_fails_closed(tmp_path):
    spec={'result_directory':str(tmp_path/'results')}
    with pytest.raises(RuntimeError, match='did not complete'):
        autopilot.check_cache_probe_completion(spec, RuntimeError('hardware preflight failed'))


def test_quarantined_diagnostic_rechecks_dispatch_before_next_campaign(tmp_path, monkeypatch):
    directory = source(tmp_path)
    root = tmp_path/'supervisor'; root.mkdir()
    spec = {'config': str(directory/'config.json'), 'prepared_directory': str(tmp_path/'prepared'),
            'result_directory': str(tmp_path/'diagnostic'), 'failure_policy':'quarantine'}
    autopilot.write(tmp_path/'prepared/correctness.json', {'success':True})
    autopilot.write(tmp_path/'prepared/build.json', {'suite':'cache'})
    dispatches, launches = [], []
    monkeypatch.setattr(autopilot.signal, 'signal', lambda *_:None)
    monkeypatch.setattr(autopilot, 'dispatch_ready', lambda cfg:dispatches.append(cfg))
    monkeypatch.setattr(autopilot, 'plan', lambda *_:config())
    monkeypatch.setattr(autopilot, 'reuse_prepared', lambda *_:None)
    monkeypatch.setattr(autopilot, 'reference_due', lambda *_:False)
    class Process:
        pid = 123
        def __init__(self, command, **kwargs):
            is_probe = 'examples.boom_cost_model.run_probes' in command
            self.code = 1 if is_probe else 0
            launches.append(command)
            assert len(dispatches) == len(launches)
            if not is_probe:
                assert (tmp_path/'diagnostic/quarantined.json').exists()
                (root/'STOP').touch()
        def poll(self): return self.code
        def wait(self): return self.code
    monkeypatch.setattr(autopilot.subprocess, 'Popen', Process)
    autopilot.supervise(directory, root, poll=0, settings={'cache_probe':spec})
    assert len(launches) == 2
    assert autopilot.read(root/'state.json')['phase'] == 'stopped'


def source(tmp_path):
    directory = tmp_path / 'previous'
    directory.mkdir()
    cfg = config()
    cfg.update(campaign_kind='cost-refine',benchmarks=['648.exchange2_s'])
    selected = {'index':0,'proposal':cfg['anchor_proposal'],'success':True,
        'compiler':{'compiler_id':'b'*64,'prefix':'/private/snapshot'},
        'train_times':{'648.exchange2_s':80.71},'speedup':82.11/80.71,'worker_index':0}
    autopilot.write(directory / 'config.json', cfg)
    autopilot.write(directory / 'result.json', {'complete':True,'incumbent_retained':True,
        'baseline_retained':False,'selected_train_proposal':selected, 'history':[selected]})
    return directory


def test_adaptive_axes_preserve_all_frozen_fields_and_integer_types():
    api = AdaptiveProposals(config())
    value = api.seed_profiles()[0]
    value['policy']['growth_budget'] = 'relaxed'
    api.validate(value)
    value['costs']['int_div'] = [1,1]
    with pytest.raises(ValueError, match='frozen'): api.validate(value)
    cfg = config()
    cfg['policy_axes']['pressure_algorithm'] = [True]
    with pytest.raises(ValueError, match='policy axis'): AdaptiveProposals(cfg)


def test_structural_interactions_keep_unlisted_fields_frozen():
    cfg=config();cfg.update(deepcopy(autopilot.FAMILIES['structural-interactions']))
    cfg['policy_axes']['growth_budget'].append(cfg['anchor_proposal']['policy']['growth_budget'])
    api=AdaptiveProposals(cfg)
    value=api.project({'branch_cost':24,'gpr_load':10,'growth_budget':'unroll_large'},'Test an interaction beyond the promising12 point.')
    assert value['costs']['branch_cost']==24
    assert value['costs']['int_mul']==api.anchor['costs']['int_mul']
    assert value['policy']['pressure_algorithm']==api.anchor['policy']['pressure_algorithm']
    with pytest.raises(ValueError,match='unknown adaptive knob'):
        api.project({'int_mul':8},'Frozen scalar cost.')


def test_reference_cache_admits_original_controls_and_excludes_selected_results(tmp_path):
    src=tmp_path/'prior';src.mkdir()
    for key,label in [('a'*64,'original'),('b'*64,'selected')]:
        autopilot.write(src/(key+'.json'),{'key':key,'source':str(tmp_path/'previous'/label/'ref/0/job')})
    dest=tmp_path/'cache'
    focused_campaign.import_baseline_cache(dest,[src],allowed_labels=('baseline-f2','baseline-heldout','original'))
    assert sorted(p.name for p in dest.glob('*.json'))==['a'*64+'.json']


def test_round_override_is_explicit_bounded_and_only_for_that_round():
    settings={'round_overrides':{'0':{'target':'648.exchange2_s','family':'structural-frontier'}}}
    assert autopilot.choose_domain([],settings)==('648.exchange2_s','structural-frontier')
    for invalid in [{'target':'unknown','family':'structural-frontier'},
            {'target':'648.exchange2_s','family':'arbitrary source'},
            {'target':'648.exchange2_s','family':'structural-frontier','extra':True}]:
        with pytest.raises(ValueError,match='override'):
            autopilot.choose_domain([],{'round_overrides':{'0':invalid}})


def test_structural_round_has_six_ablations_control_and_feedback(tmp_path,monkeypatch):
    directory=source(tmp_path);review=autopilot.review(directory);cfg=config()
    monkeypatch.setattr(autopilot,'confirmed_anchor',lambda *_:(None,review['selected']))
    monkeypatch.setattr(autopilot.pressure_proposals,'request_json',lambda *_:pytest.fail('structured seeds must not be attributed to Claude'))
    planned=autopilot.plan(cfg,[review],tmp_path/'next',{'deadline_mode':True,
        'round_overrides':{'1':{'target':'648.exchange2_s','family':'structural-frontier'}}})
    seeds=AdaptiveProposals(planned).seed_profiles()
    assert len(seeds)==7 and planned['campaign_budget']==8
    assert planned['prepare_seed_count']==7
    assert seeds[0]==review['selected']['proposal']
    assert all(p['costs']==seeds[0]['costs'] and p['move_profile']==seeds[0]['move_profile'] for p in seeds)
    assert len(planned['policy_axes']['growth_budget'])==9


def test_optimization_portfolio_waits_for_all_five_ablations_before_interactions(tmp_path,monkeypatch):
    directory=source(tmp_path);review=autopilot.review(directory);cfg=config()
    review['selected']['proposal']['policy']['growth_budget']='unroll'
    monkeypatch.setattr(autopilot,'confirmed_anchor',lambda *_:(None,review['selected']))
    monkeypatch.setattr(autopilot.pressure_proposals,'request_json',lambda *_:pytest.fail('structured seeds are not LLM proposals'))
    planned=autopilot.plan(cfg,[review],tmp_path/'next',{'deadline_mode':True,
        'round_overrides':{'1':{'target':'648.exchange2_s','family':'optimization-portfolio'}}})
    seeds=AdaptiveProposals(planned).seed_profiles()
    assert len(seeds)==6 and planned['campaign_budget']==9
    assert planned['prepare_seed_count']==planned['feedback_min_completed']==6
    assert len(planned['policy_axes']['growth_budget'])==10
    assert all(p['costs']==seeds[0]['costs'] and p['move_profile']==seeds[0]['move_profile'] for p in seeds)


def test_cloning_factorial_has_two_isolated_limits_and_their_interaction(tmp_path,monkeypatch):
    directory=source(tmp_path);review=autopilot.review(directory);cfg=config()
    review['selected']['proposal']['policy']['growth_budget']='unroll'
    monkeypatch.setattr(autopilot,'confirmed_anchor',lambda *_:(None,review['selected']))
    monkeypatch.setattr(autopilot.pressure_proposals,'request_json',lambda *_:pytest.fail('factorial seeds are deterministic'))
    planned=autopilot.plan(cfg,[review],tmp_path/'next',{'deadline_mode':True,
        'round_overrides':{'1':{'target':'648.exchange2_s','family':'cloning-frontier'}}})
    seeds=AdaptiveProposals(planned).seed_profiles()
    assert len(seeds)==planned['campaign_budget']==planned['feedback_min_completed']==4
    assert [p['policy']['growth_budget'] for p in seeds[1:]]==[
        'unroll_clone_growth','unroll_clone_threshold','unroll_clone_growth_threshold']
    assert all(p['costs']==seeds[0]['costs'] and p['move_profile']==seeds[0]['move_profile'] for p in seeds)


def test_novel_menu_excludes_known_profiles_and_preserves_frozen_fields():
    api=AdaptiveProposals(config())
    known={api.identity(p) for p in api.seed_profiles()}
    menu=autopilot.untested_knobs(api,known)
    assert menu
    profiles=[api.project(k,'An isolated bounded contrast; unchanged code rejects the mechanism.') for k in menu]
    ids=[api.identity(p) for p in profiles]
    assert len(ids)==len(set(ids)) and not set(ids)&known
    assert all(p['costs']['int_mul']==api.anchor['costs']['int_mul'] for p in profiles)


def test_invalid_planner_retries_use_explicitly_labeled_valid_fallback(tmp_path,monkeypatch):
    directory=source(tmp_path);review=autopilot.review(directory);cfg=config()
    monkeypatch.setattr(autopilot,'confirmed_anchor',lambda *_:(None,review['selected']))
    def request(config,prompt,destination,validator):
        assert prompt['tested_knobs'] and prompt['untested_knob_examples']
        assert 'reference_speedup' not in json.dumps(prompt)
        return validator({'hypothesis':'A repeated invalid control',
            'seeds':[prompt['example_profile']]*3})
    monkeypatch.setattr(autopilot.pressure_proposals,'request_json',request)
    planned=autopilot.plan(cfg,[review],tmp_path/'next',{'round_overrides':{
        '1':{'target':'648.exchange2_s','family':'branch-growth'}}})
    seeds=AdaptiveProposals(planned).seed_profiles()
    assert len(seeds)==4 and len({autopilot.pressure_proposals.profile_identity(p) for p in seeds})==4
    report=autopilot.read(tmp_path/'next/planner-fallback.json')
    assert report['model_generated'] is False
    assert all('not a model proposal' in p['rationale'] for p in seeds[1:])


def test_explicit_coordinator_restart_clears_old_flags_and_still_honors_stop_files(tmp_path,monkeypatch):
    directory=source(tmp_path);root=tmp_path/'supervisor';root.mkdir()
    autopilot.write(root/'state.json',{'reviews':[autopilot.review(directory)],'current':str(directory),
        'stop_requested':True,'failure':'historical','blocker':'historical'})
    monkeypatch.setattr(autopilot.signal,'signal',lambda *_:None)
    monkeypatch.setattr(autopilot,'plan',lambda *_:config())
    monkeypatch.setattr(autopilot,'reuse_prepared',lambda *_:None)
    checked=[]
    def dispatch(_):
        snapshot=autopilot.read(root/'state.json')
        assert not any(k in snapshot for k in ('stop_requested','failure','blocker'))
        (root/'STOP').touch();checked.append(True)
    monkeypatch.setattr(autopilot,'dispatch_ready',dispatch)
    monkeypatch.setattr(autopilot.subprocess,'Popen',lambda *_a,**_k:pytest.fail('STOP forbids launch'))
    autopilot.supervise(directory,root,poll=0)
    assert checked and (root/'STOP').exists()
    assert autopilot.read(root/'state.json')['phase']=='stopped'


def test_mechanistic_portfolio_has_three_isolated_treatments_and_one_feedback_slot(tmp_path,monkeypatch):
    directory=source(tmp_path);review=autopilot.review(directory);cfg=config()
    anchor=review['selected']['proposal'];anchor['policy']['growth_budget']='unroll'
    anchor['costs']['int_mul']=[3,3]
    before=deepcopy(anchor)
    monkeypatch.setattr(autopilot,'confirmed_anchor',lambda *_:(None,review['selected']))
    monkeypatch.setattr(autopilot.pressure_proposals,'request_json',lambda *_:pytest.fail('structured ablations are not LLM proposals'))
    planned=autopilot.plan(cfg,[review],tmp_path/'next',{'deadline_mode':True,
        'round_overrides':{'1':{'target':'648.exchange2_s','family':'mechanistic-portfolio'}}})
    seeds=AdaptiveProposals(planned).seed_profiles()
    assert len(seeds)==4 and planned['campaign_budget']==5 and planned['prepare_seed_count']==4
    assert planned['feedback_min_completed']==4
    assert anchor==before==seeds[0]
    assert seeds[1]['costs']['int_mul']==[4,4]
    assert seeds[1]['policy']==anchor['policy']
    assert [p['policy']['growth_budget'] for p in seeds[2:]]==['unroll_no_presched','unroll_tracer']
    assert all(p['costs']==anchor['costs'] for p in seeds[2:])
    assert all(p['move_profile']==anchor['move_profile'] for p in seeds)
    assert all(p['costs']['branch_cost']==anchor['costs']['branch_cost'] for p in seeds)


def test_mechanistic_treatments_preserve_inline_anchor_and_reject_nested_ablations():
    anchor=config()['anchor_proposal'];anchor['policy']['growth_budget']='inline_selective'
    treatments=autopilot.mechanistic_seeds(anchor)
    assert treatments[1]['policy']['growth_budget']=='inline_selective_no_presched'
    assert treatments[2]['policy']['growth_budget']=='inline_selective_tracer'
    anchor['policy']['growth_budget']='unroll_tracer'
    with pytest.raises(ValueError,match='without a pass ablation'):autopilot.mechanistic_seeds(anchor)


def test_direct_planner_honors_requested_model_without_mutating_legacy_base(tmp_path,monkeypatch):
    directory=source(tmp_path);review=autopilot.review(directory);base=config()
    monkeypatch.setattr(autopilot,'confirmed_anchor',lambda *_:(None,review['selected']))
    planned=autopilot.plan(base,[review],tmp_path/'next',{'deadline_mode':True,
        'llm_model':'claude-opus-5-5','llm_effort':'xhigh',
        'round_overrides':{'1':{'target':'648.exchange2_s','family':'mechanistic-portfolio'}}})
    assert planned['model']=='claude-opus-5-5' and planned['llm_effort']=='xhigh'
    assert base['model']=='test' and 'llm_effort' not in base


def test_delta_projection_changes_only_allowed_axes_and_copies_anchor():
    api = AdaptiveProposals(config())
    value=api.project({'branch_cost':4,'growth_budget':'relaxed'},'Test the branch/growth interaction.')
    assert value['costs']['int_mul']==api.anchor['costs']['int_mul']
    assert value['policy']['growth_budget']=='relaxed'
    value['costs']['fp_add'][0]=999
    assert api.anchor['costs']['fp_add']==[4,4]
    with pytest.raises(ValueError,match='unknown adaptive knob'):
        api.project({'int_mul':4},'Cannot replace a frozen cost with a screening winner.')
    with pytest.raises(ValueError,match='enumerated'):
        api.project({'branch_cost':5},'Off grid.')


def test_adaptive_cli_delta_response_is_projected_without_exposing_private_config(tmp_path,monkeypatch):
    from examples.boom_cost_model import pressure_proposals
    cfg={**config(),'private_config_value':'PRIVATE_SENTINEL'}
    class LLM:
        def __init__(self,**kwargs):
            assert kwargs['extra_cli_args']==['--tools','','--strict-mcp-config']
            assert not kwargs['dangerously_skip_permissions']
        def prompt(self,prompt,tools):
            assert tools==[] and 'PRIVATE_SENTINEL' not in prompt
            return SimpleNamespace(success=True,result=json.dumps({'knobs':{'branch_cost':4},'rationale':'Isolate branch selection.'}))
    monkeypatch.setattr(pressure_proposals,'ClaudeCodeLLM',LLM)
    api=AdaptiveProposals(cfg)
    result=api.feedback_proposal(cfg,[],[],tmp_path)
    assert result['costs']['branch_cost']==4
    assert result['costs']['int_mul']==api.anchor['costs']['int_mul']


def test_joint_search_explicitly_allows_screened_cost_without_replacing_control():
    cfg=config()
    cfg.update(deepcopy(autopilot.FAMILIES['joint-costs']))
    cfg['anchor_proposal']['costs'].update(int_mul=[3,3],branch_cost=4)
    alternative=deepcopy(cfg['anchor_proposal'])
    alternative['costs']['int_mul']=[4,4]
    cfg['adaptive_seeds']=[cfg['anchor_proposal'],alternative]
    api=AdaptiveProposals(cfg)
    value=api.project({'int_mul':4,'gpr_store':8},'Test the screened arithmetic setting with a store-cost interaction.')
    assert value['costs']['int_mul']==[4,4]
    assert api.seed_profiles()[0]['costs']['int_mul']==[3,3]


def test_adaptive_mode_limits_benchmarks_and_reserved_keys():
    focused_campaign.validate_config(config())
    assert isinstance(focused_campaign.proposal_api(config()),AdaptiveProposals)
    for change in ({'benchmarks':['unknown']},{'benchmarks':['641.leela_s','602.gcc_s']},
                   {'reserved_profile_ids':['not-a-hash']}):
        with pytest.raises(ValueError): focused_campaign.validate_config({**config(),**change})


def test_review_waits_for_owner_lock_and_rejects_stale_result(tmp_path):
    directory = source(tmp_path)
    with (directory / 'controller.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert not autopilot.controller_idle(directory)
        with pytest.raises(ValueError,match='still active'): autopilot.review(directory)
    review = autopilot.review(directory)
    assert review['validated_selection'] and review['selected']['train_times']['648.exchange2_s'] == 80.71
    autopilot.write(directory / 'failure.json',{'failure':'later failed invocation'})
    with pytest.raises(ValueError,match='predates'): autopilot.review(directory)


def test_target_and_family_rotation_avoids_single_idea():
    reviews = [{'benchmarks':['648.exchange2_s'],'family':'allocation-memory'}]
    seen = {('648.exchange2_s','allocation-memory')}
    for _ in range(8):
        target,family = autopilot.choose_domain(reviews)
        assert (target,family) not in seen
        seen.add((target,family))
        reviews.append({'benchmarks':[target],'family':family})
    assert len(seen) == 9


def test_cross_target_compiler_transfer_does_not_transfer_confirmation(tmp_path):
    directory = source(tmp_path)
    review = autopilot.review(directory)
    regression = deepcopy(review)
    regression.update(benchmarks=['641.leela_s'],validated_selection=False)
    regression['selected']['compiler']['compiler_id'] = 'c'*64
    primary, selected = autopilot.confirmed_anchor([review,regression],'641.leela_s',{})
    assert primary is None
    assert selected['compiler']['compiler_id'] == 'b'*64


def test_planner_enforces_new_bounded_profiles_and_excludes_reference_feedback(tmp_path,monkeypatch):
    directory = source(tmp_path)
    review = autopilot.review(directory)
    cfg = json.loads((directory / 'config.json').read_text())
    def request(config,prompt,destination,validator):
        assert prompt['task'].endswith('641.leela_s')
        assert 'reference_speedup' not in json.dumps(prompt)
        seeds = []
        for branch,growth in ((2,'default'),(3,'compact'),(4,'relaxed')):
            value = deepcopy(prompt['example_profile'])
            value['costs']['branch_cost'] = branch
            value['policy']['growth_budget'] = growth
            seeds.append(value)
        bad = deepcopy(seeds)
        bad[0]['costs']['fp_add'] = [1,1]
        with pytest.raises(ValueError): validator({'hypothesis':'bad','seeds':bad})
        with pytest.raises(ValueError): validator({'hypothesis':'duplicate','seeds':[seeds[0]]*3})
        return validator({'hypothesis':'Test branching versus growth.','seeds':seeds})
    monkeypatch.setattr(autopilot.pressure_proposals,'request_json',request)
    planned = autopilot.plan(cfg,[review],tmp_path / 'next')
    assert planned['campaign_kind'] == 'adaptive'
    assert len(AdaptiveProposals(planned).seed_profiles()) == 4
    assert not planned.get('incumbent_run')


def test_prepared_reuse_is_copy_and_rejects_changed_archive(tmp_path):
    directory = source(tmp_path)
    cfg = json.loads((directory / 'config.json').read_text())
    cfg['benchmarks'] = ['648.exchange2_s']
    cfg['campaign_kind'] = 'adaptive'
    prepared = directory / 'baseline-prepared'
    (prepared / 'train').mkdir(parents=True)
    archive = prepared / 'train/workload.tar.gz'
    archive.write_bytes(b'immutable workload')
    autopilot.write(prepared / 'prepared.json',{'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest()})
    review = autopilot.review(directory)
    dest = tmp_path / 'next/run'
    autopilot.reuse_prepared(cfg,[review],dest)
    copy = dest / 'baseline-prepared/train/workload.tar.gz'
    assert copy.read_bytes() == archive.read_bytes() and copy.stat().st_ino != archive.stat().st_ino
    archive.write_bytes(b'corrupted')
    with pytest.raises(ValueError,match='bytes changed'):
        autopilot.reuse_prepared(cfg,[review],tmp_path / 'another/run')


def test_supervisor_stops_without_touching_owner_controller(tmp_path,monkeypatch):
    directory = source(tmp_path)
    root = tmp_path / 'supervisor'
    root.mkdir()
    monkeypatch.setattr(autopilot,'controller_idle',lambda *_:False)
    monkeypatch.setattr(autopilot.time,'sleep',lambda *_:(root / 'STOP').touch())
    monkeypatch.setattr(autopilot.signal,'signal',lambda *_:None)
    monkeypatch.setattr(autopilot.subprocess,'Popen',lambda *_a,**_k:pytest.fail('must not launch'))
    autopilot.supervise(directory,root,poll=0)
    assert autopilot.read(root / 'state.json')['phase'] == 'stopped'


def test_supervisor_does_not_dispatch_after_missing_result(tmp_path,monkeypatch):
    directory = source(tmp_path)
    (directory / 'result.json').unlink()
    root = tmp_path / 'supervisor'
    root.mkdir()
    monkeypatch.setattr(autopilot.signal,'signal',lambda *_:None)
    monkeypatch.setattr(autopilot.subprocess,'Popen',lambda *_a,**_k:pytest.fail('must not launch'))
    with pytest.raises(RuntimeError,match='without result'):
        autopilot.supervise(directory,root,poll=0)
    assert autopilot.read(root / 'state.json')['phase'] == 'blocked'


def test_supervisor_applies_requested_model_policy_to_new_plans(tmp_path,monkeypatch):
    directory=source(tmp_path)
    root=tmp_path/'supervisor';root.mkdir()
    seen={}
    settings={'llm_model':'claude-opus-5-5','llm_effort':'xhigh'}
    def plan(base,reviews,dest,policy):
        seen.update({k:base[k] for k in ('model','llm_effort')})
        (root/'STOP').touch()
        return {**config(),'model':base['model'],'llm_effort':base['llm_effort']}
    monkeypatch.setattr(autopilot,'plan',plan)
    monkeypatch.setattr(autopilot,'reuse_prepared',lambda *_:None)
    monkeypatch.setattr(autopilot.signal,'signal',lambda *_:None)
    monkeypatch.setattr(autopilot.subprocess,'Popen',lambda *_a,**_k:pytest.fail('stop prevents launch'))
    autopilot.supervise(directory,root,poll=0,settings=settings)
    assert seen=={'model':'claude-opus-5-5','llm_effort':'xhigh'}


def test_queued_model_mismatch_is_rejected_without_rewriting_history(tmp_path,monkeypatch):
    directory=source(tmp_path)
    root=tmp_path/'supervisor';root.mkdir()
    old=config()
    autopilot.write(root/'round-001/config.json',old)
    monkeypatch.setattr(autopilot.signal,'signal',lambda *_:None)
    monkeypatch.setattr(autopilot.subprocess,'Popen',lambda *_a,**_k:pytest.fail('must not launch'))
    with pytest.raises(ValueError,match='queued LLM configuration differs'):
        autopilot.supervise(directory,root,poll=0,settings={'llm_model':'claude-opus-5-5','llm_effort':'xhigh'})
    assert autopilot.read(root/'round-001/config.json')==old


def test_resume_model_mismatch_cannot_silently_fall_back(tmp_path,monkeypatch):
    directory=source(tmp_path)
    root=tmp_path/'supervisor';root.mkdir()
    resumed=tmp_path/'resumed/run';resumed.mkdir(parents=True)
    autopilot.write(resumed.parent/'config.json',config())
    monkeypatch.setattr(autopilot.signal,'signal',lambda *_:None)
    monkeypatch.setattr(autopilot.subprocess,'Popen',lambda *_a,**_k:pytest.fail('must not launch'))
    with pytest.raises(ValueError,match='resumed LLM configuration differs'):
        autopilot.supervise(directory,root,poll=0,resume_run=resumed,
            settings={'llm_model':'claude-opus-5-5','llm_effort':'xhigh'})


@pytest.mark.parametrize('status',[0,255])
def test_preflight_never_takes_over_busy_or_unreachable_driver(status,monkeypatch):
    cfg = {**config(),'aws_profile':'test','region':'us-east-1',
           'fpga_workers':[{'instance_id':'i-owned','ssh_alias':'owned'}]}
    calls = []
    def run(command,**kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=status if command[0] == 'ssh' else 0)
    monkeypatch.setattr(autopilot.subprocess,'run',run)
    with pytest.raises(RuntimeError,match='occupied or idle state unverifiable'):
        autopilot.dispatch_ready(cfg)
    assert calls[-1][-1] == 'pgrep -x FireSim-f2'
    assert 'StrictHostKeyChecking=yes' in calls[-1]


@pytest.mark.parametrize('resume',[False,True])
def test_supervisor_stop_signals_only_owned_child_and_drains_it(tmp_path,monkeypatch,resume):
    directory = source(tmp_path)
    report = autopilot.read(directory / 'result.json')
    report['baseline_retained'] = True  # No reference phase for an unconfirmed transfer.
    autopilot.write(directory / 'result.json',report)
    root = tmp_path / 'supervisor'
    root.mkdir()
    signals,children = [],[]
    def plan(base,reviews,dest):
        autopilot.write(dest / 'config.json',config())
        return config()
    class Child:
        pid = 123456789
        def __init__(self,command,**kwargs):
            assert kwargs['start_new_session']
            children.append(command)
            self.done = False
        def poll(self):
            (root / 'STOP').touch()
            return 0 if self.done else None
        def wait(self):
            self.done = True
            return 0
    monkeypatch.setattr(autopilot,'plan',plan)
    monkeypatch.setattr(autopilot,'reuse_prepared',lambda *_:None)
    monkeypatch.setattr(autopilot,'dispatch_ready',lambda *_:None)
    monkeypatch.setattr(autopilot.subprocess,'Popen',Child)
    monkeypatch.setattr(autopilot.os,'killpg',lambda pid,sig:signals.append((pid,sig)))
    monkeypatch.setattr(autopilot.signal,'signal',lambda *_:None)
    resume_run = None
    if resume:
        resume_run = tmp_path/'resumed/run'
        resume_run.mkdir(parents=True)
        autopilot.write(resume_run.parent/'config.json',config())
    autopilot.supervise(directory,root,poll=0,resume_run=resume_run)
    assert len(children) == 1
    assert signals == [(Child.pid,autopilot.signal.SIGINT)]
    assert autopilot.read(root / 'state.json')['phase'] == 'stopped'


def test_resume_refuses_changed_snapshot_without_dispatch(tmp_path,monkeypatch):
    directory = source(tmp_path)
    root = tmp_path/'supervisor'
    root.mkdir()
    resumed = tmp_path/'resumed/run'
    resumed.mkdir(parents=True)
    autopilot.write(resumed.parent/'config.json',config())
    autopilot.write(resumed/'config.json',{**config(),'train_timeout_seconds':12345})
    monkeypatch.setattr(autopilot.signal,'signal',lambda *_:None)
    monkeypatch.setattr(autopilot.subprocess,'Popen',lambda *_a,**_k:pytest.fail('must not launch'))
    with pytest.raises(ValueError,match='immutable snapshot'):
        autopilot.supervise(directory,root,poll=0,resume_run=resumed)


def test_resume_refuses_already_completed_run(tmp_path):
    directory = source(tmp_path)
    root = tmp_path/'supervisor'
    root.mkdir()
    with pytest.raises(ValueError,match='active or already complete'):
        autopilot.supervise(directory,root,poll=0,resume_run=directory)


def test_prepare_only_stop_drains_current_preparation_before_next_dispatch(tmp_path,monkeypatch):
    handlers,calls = {},[]
    monkeypatch.setattr(focused_campaign.signal,'signal',lambda signum,handler:handlers.update({signum:handler}))
    def prepare(*args):
        calls.append(args[1])
        handlers[focused_campaign.signal.SIGINT]()
        return {}
    monkeypatch.setattr(focused_campaign,'prepare',prepare)
    with pytest.raises(focused_campaign.CampaignStopped):
        focused_campaign.run(config(),tmp_path,prepare_only=True)
    assert calls == [tmp_path / 'baseline-prepared']


def test_reference_check_pairs_original_and_winner_on_each_worker(tmp_path,monkeypatch):
    directory = source(tmp_path)
    root = tmp_path / 'reference'
    root.mkdir()
    selected = autopilot.read(directory / 'result.json')['selected_train_proposal']
    class Experiment:
        def __init__(self,cfg,dest):
            self.config,self.directory,self.hardware = cfg,dest,{}
            dest.mkdir(parents=True,exist_ok=True)
        def workload(self,compiler,inputs,dest):
            assert inputs == 'ref'
            return compiler
    def prepare(cfg,dest,index=None,proposal=None):
        return {'compiler':selected['compiler'] if proposal else {'compiler_id':'original','prefix':'baseline'}}
    calls = []
    def measure(ex,item,name,**kwargs):
        assert kwargs['inputs'] == 'ref'
        calls.append((ex.workers[0]['instance_id'],name))
        return {'times':{'648.exchange2_s':100 if name == 'original' else 90}}
    monkeypatch.setattr(reference_check,'Experiment',Experiment)
    monkeypatch.setattr(reference_check,'verified_workers',lambda *_:[{'instance_id':'a'},{'instance_id':'b'}])
    monkeypatch.setattr(reference_check,'prepare',prepare)
    monkeypatch.setattr(reference_check,'measure',measure)
    monkeypatch.setattr(reference_check.signal,'signal',lambda *_:None)
    reference_check.run(directory,root)
    result = autopilot.read(root / 'result.json')
    assert result['reference_checked'] and not result['SPEC_reportable_score']
    assert [r['reference_speedup'] for r in result['workers']] == [100/90]*2
    assert [name for worker,name in calls if worker == 'a'] == ['original','selected']
    assert [name for worker,name in calls if worker == 'b'] == ['selected','original']
