"""Continuous, explicitly authorized experiment succession; stop with a STOP file.

Completed train evidence selects a target/family and constrains a data-only
Claude planner. Existing controllers retain every correctness/network/hardware
gate. The supervisor never kills an unowned process or retries a failed workload.
"""

import argparse
from copy import deepcopy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import traceback

from examples.boom_cost_model.adaptive_proposals import AdaptiveProposals
from examples.boom_cost_model import focused_campaign, pressure_proposals

TARGETS = ("648.exchange2_s", "641.leela_s", "602.gcc_s")
FAMILIES = {
    "branch-growth": {
        "cost_axes": {"branch_cost": [2, 3, 4, 6, 8, 12]},
        "policy_axes": {"growth_budget": ["default", "compact", "tight", "relaxed", "peel_only", "jam_only"]},
        "hypothesis": "Branch avoidance and code expansion compete with frontend footprint and useful ILP; the prior peel32 and peel128 regressions argue against monotonic assumptions."},
    "integer-idioms": {
        "cost_axes": {"int_mul": [2, 3, 4, 6, 8], "int_div": [3, 6, 12, 24, 48]},
        "policy_axes": {},
        "hypothesis": "Change strength-reduction and expression selection around multiply/divide without changing scheduler latency or ISA. Inspect actual generated-code differences; these are heuristic costs."},
    "allocation-memory": {
        "cost_axes": {"memory_cost": [3, 5, 7, 9, 12], "gpr_load": [3, 4, 6, 8, 12], "gpr_store": [3, 4, 6, 8, 12]},
        "policy_axes": {"pressure_algorithm": [0, 1, 2], "ira_loop_pressure": [False, True]},
        "hypothesis": "Test spill/rematerialization and scheduling/allocation interactions. Physical renaming does not eliminate architectural register pressure; static estimates do not measure dynamic spills."},
    "codegen-growth": {
        "cost_axes": {},
        "policy_axes": {"growth_budget": ["compact", "inline", "unroll", "inline_unroll"]},
        "hypothesis": "Test larger structural changes: raise automatic inlining limits, enable bounded ordinary loop unrolling, and their interaction. Four-wide BOOM may benefit from exposed ILP and fewer calls/branches, but register pressure and instruction footprint may regress. Baseline O3 already inlines but disables ordinary -funroll-loops. Preserve the proven pressure/peel policy."},
    "joint-costs": {
        "cost_axes": {"int_mul":[3,4],"branch_cost":[4,8],"memory_cost":[5,7,9],
            "gpr_load":[6,8,10],"gpr_store":[6,8,10]},
        "policy_axes": {"pressure_algorithm":[0,2],"ira_loop_pressure":[False,True]},
        "hypothesis": "Explore interactions around the confirmed unroll winner and the faster, unconfirmed int_mul4 screening point. Preserve the actual confirmed control; do not silently promote the screening profile. Use controlled comparisons for branch selection and allocation costs, keeping growth/ISA/flags/libraries/hardware fixed."},
    "structural-frontier": {
        "cost_axes": {},
        "policy_axes": {"growth_budget": ['unroll_small','unroll_large','unroll_xlarge',
            'inline_selective','inline_selective_large','inline_small_large',
            'inline_selective_xlarge','inline_small_small']},
        "hypothesis": "Test a broad instruction-footprint/ILP frontier: smaller, double and quadruple ordinary-unroll budgets; moderate automatic inlining; their interaction; and a smaller-inline counterpoint. Preserve all scalar costs, pressure policy, peel/jam settings, ISA/ABI and hardware. Inlining180/growth80 previously regressed; moderate80/growth30 is a different intervention. Cache capacity and static code size do not prove a cache bottleneck."},
    "structural-interactions": {
        "cost_axes": {"branch_cost":[2,4,8,12], "gpr_load":[6,8,10]},
        "policy_axes": {"growth_budget":['unroll','unroll_small','unroll_large','unroll_xlarge',
            'inline_selective','inline_selective_large','inline_small_large']},
        "hypothesis": "Use the latest confirmed structural winner as anchor. Test branch avoidance and spill-load heuristics jointly with loop/inlining footprint. The branch-cost12 screening point suggests nonmonotonic interactions; do not assume bigger or smaller costs always help. Select informative contrasts from measured train evidence; freeze every other field."},
}
MICROARCH = {
    "BOOM_revision": "5223e44cfeb26f41380057a2eb4d651197475f69",
    "configuration": "WithNMegaBooms, BOOM V3",
    "fetch_width": 8, "decode_retire_width": 4, "ROB_entries": 128,
    "issue_widths": {"integer": 4, "memory": 2, "FP": 2},
    "issue_queue_entries": {"integer": 40, "memory": 24, "FP": 32},
    "physical_registers_each": 128, "load_store_queue_entries_each": 32,
    "max_branches": 20, "Dcache_MSHRs": 8,
    "cache_hierarchy": {"L1I_KiB": 32, "L1D_KiB": 32, "L1_ways": 8,
        "line_bytes": 64, "LLC_MiB": 4,
        "provenance": "Pinned WithNMegaBooms: 64 sets x 8 ways x 64 B; pinned Rocket defaults and FRFCFS/LLC4MB image."},
    "limitations": "Source configuration, not runtime occupancy or bottleneck measurements. No RVV. No measured application cross-file moves. Generic microkernel ranking failed SPEC validation."}


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    """Atomically publish local supervisor state without partial JSON reads."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(value, indent=2) + '\n')
    temp.replace(path)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def controller_idle(source):
    """Observe the existing controller lock; never unlock or signal its owner."""
    path = Path(source) / 'controller.lock'
    if not path.exists():
        return True
    with path.open('r') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
    return True


def review(source):
    """Accept only complete, drained runs and retain measured train evidence."""
    source = Path(source)
    if not controller_idle(source):
        raise ValueError('controller is still active')
    result = read(source / 'result.json')
    if not result.get('complete'):
        raise ValueError('run did not complete')
    for path in list(source.glob('invocations/*.json')) + [source / 'failure.json', source / 'stopped.json']:
        if path.exists() and path.stat().st_mtime_ns > (source / 'result.json').stat().st_mtime_ns:
            raise ValueError('result predates a later invocation, failure or stop')
    # Failed/rejected candidates remain evidence, but never become incumbents.
    selected = result.get('selected_train_proposal') or result.get('best_train_proposal')
    if selected and not selected.get('success'):
        raise ValueError('selected compiler did not pass')
    observations = [{k: row[k] for k in ('index', 'proposal', 'success', 'train_times',
        'speedup', 'skipped', 'failure', 'code_generation') if k in row} for row in result['history']]
    for row in observations:
        prepared = source / f"candidate-{row['index']:03d}" / 'prepared.json'
        if prepared.exists():
            row['code_generation'] = read(prepared)['code_generation']
    return {'source': str(source.resolve()), 'result_sha256': digest(source / 'result.json'),
        'benchmarks': read(source / 'config.json')['benchmarks'],
        'family': read(source / 'config.json').get('hypothesis_family', 'allocation-memory'),
        'deadline_mode': read(source / 'config.json').get('deadline_mode',False),
        'incumbent_retained': result.get('incumbent_retained'),
        'confirmed_train_speedup': result.get('confirmed_train_speedup'),
        'confirmed_incremental_speedup': result.get('confirmed_incremental_speedup'),
        'validated_selection': bool(selected and not result.get('baseline_retained') and (
            result.get('incumbent_retained') or result.get('train_confirmation_checked') and not result.get('confirmation_failed'))),
        'reference_checked': result.get('reference_checked', False), 'observations': observations,
        'selected': selected}


def choose_domain(reviews, settings=None):
    """Rotate targets and hypothesis families; never pursue one family endlessly."""
    overrides = (settings or {}).get('round_overrides', {})
    if not isinstance(overrides, dict) or any(not isinstance(k,str) or not k.isdecimal() or
            not isinstance(v,dict) or v.keys() != {'target','family'} or
            v['target'] not in TARGETS or v['family'] not in FAMILIES for k,v in overrides.items()):
        raise ValueError('invalid explicit round domain override')
    selected = overrides.get(str(len(reviews)))
    if selected:
        return selected['target'], selected['family']
    if settings and settings.get('deadline_mode'):
        index = sum(bool(r.get('deadline_mode')) for r in reviews)
        targets = settings.get('target_schedule', ['648.exchange2_s','648.exchange2_s','641.leela_s'])
        families = settings.get('family_schedule', ['codegen-growth','integer-idioms','branch-growth','allocation-memory'])
        if not targets or any(t not in TARGETS for t in targets) or not families or any(f not in FAMILIES for f in families):
            raise ValueError('invalid deadline target/family schedule')
        return targets[index % len(targets)], families[index % len(families)]
    counts = {(target, family): sum(r['benchmarks'] == [target] and r['family'] == family for r in reviews)
              for target in TARGETS for family in FAMILIES}
    # Prefer a different target after the initial cost round; overfitting one
    # small train workload is a larger unknown than another local cost tweak.
    target_order = ("641.leela_s", "602.gcc_s", "648.exchange2_s")
    return min(counts, key=lambda pair: (counts[pair],
        sum(r['benchmarks'] == [pair[0]] for r in reviews),
        target_order.index(pair[0]), list(FAMILIES).index(pair[1])))


def confirmed_anchor(reviews, target, base):
    """Choose a confirmed incumbent for this benchmark, never transfer its score."""
    sources = [Path(r['source']) for r in reviews]
    if base.get('incumbent_run'):
        sources.append(Path(base['incumbent_run']))
    candidates = []
    for source in dict.fromkeys(sources):
        result = read(source / 'result.json')
        if read(source / 'config.json')['benchmarks'] != [target]:
            continue
        if result.get('complete') and result.get('train_confirmation_checked') and not (
                result.get('confirmation_failed') or result.get('baseline_retained')):
            best = result.get('best_train_proposal')
            selected = result.get('selected_train_proposal', best)
            if best and selected and best.get('success') and best['compiler'] == selected['compiler']:
                candidates.append((result['confirmed_train_speedup'], source, best))
    if candidates:
        _, source, selected = max(candidates, key=lambda x: x[0])
        return source, selected
    # The compiler may transfer to a new workload; its measured speedup may not.
    fallback = next((r['selected'] for r in reversed(reviews)
                     if r.get('selected') and r.get('validated_selection')), None)
    if fallback is None:
        raise ValueError('no validated compiler profile available to seed a new target')
    return None, fallback


def train_timeout(target, requested=5400):
    """Budget slower train workloads explicitly; keep immutable run configs honest.

    Leela completed after about 6,311 wall seconds on this image, beyond the
    old 5,400-second manager limit. The user requested no short run timeouts;
    allow at least 24 hours. This changes the wall-clock allowance, never guest
    inputs, flags, or timing cache keys. Status checks remain read-only.
    """
    if target not in TARGETS or type(requested) is not int or not 60 <= requested <= 604800:
        raise ValueError('invalid benchmark or requested train timeout')
    return max(requested,86400)


def plan(base, reviews, directory, settings=None):
    """Ask Claude for controlled tests, then validate every field before execution."""
    target, family = choose_domain(reviews, settings)
    source, selected = confirmed_anchor(reviews, target, base)
    cfg = deepcopy(base)
    for name in ('cost_seeds', 'adaptive_seeds', 'incumbent_run', 'incumbent_result_sha256',
                 'incumbent_compiler_id', 'incumbent_supporting_runs'):
        cfg.pop(name, None)
    cfg.update(deepcopy(FAMILIES[family]))
    cfg.update(campaign_kind='adaptive-refine' if source else 'adaptive',
        benchmarks=[target], anchor_proposal=selected['proposal'], hypothesis_family=family,
        campaign_budget=6, iterations=6, final_ref=False, confirmation_worker_index=1)
    cfg['train_timeout_seconds'] = train_timeout(target,base.get('train_timeout_seconds',5400))
    deadline = bool(settings and settings.get('deadline_mode'))
    if deadline:
        cfg.update(deadline_mode=True,campaign_budget=4,iterations=4,feedback_min_completed=2)
    for name, choices in cfg['cost_axes'].items():
        group = 'move_profile' if name.startswith('gpr_') else 'costs'
        value = selected['proposal'][group][name]
        value = value[0] if isinstance(value, list) else value
        if value not in choices:
            choices.append(value)
    for name, choices in cfg['policy_axes'].items():
        value = selected['proposal']['policy'][name]
        if value not in choices:
            choices.append(value)
    cfg['baseline_cache_dirs'] = list(dict.fromkeys(
        base.get('baseline_cache_dirs', []) + [str(p) for r in reviews
            for p in Path(r['source']).glob('worker-*/measurement-cache')]))
    if source:
        cfg.update(incumbent_run=str(source), incumbent_result_sha256=digest(source / 'result.json'),
                   incumbent_compiler_id=selected['compiler']['compiler_id'])
        cfg['incumbent_supporting_runs'] = [{'run_dir': r['source'], 'result_sha256': r['result_sha256']}
            for r in reviews if r['benchmarks'] == [target] and r.get('selected') and
                r['selected']['compiler']['compiler_id'] == selected['compiler']['compiler_id'] and Path(r['source']) != source][-4:]
    # Existing train observations are context; reference results never enter a prompt.
    cfg['analysis_evidence'] = {'microarchitecture': MICROARCH,
        'earlier_analysis': base.get('analysis_evidence', {}),
        # Full history stays in state.json; bound recurring model context/cost.
        'recent_train_reviews': [{k:r[k] for k in ('benchmarks','family','observations')} for r in reviews[-9:]]}
    anchor = deepcopy(selected['proposal'])
    # Instantiate the validator with a temporary second valid point. The real
    # planner must supply three distinct, previously untested profiles.
    alternative = deepcopy(anchor)
    group, axes = ('costs', cfg['cost_axes']) if cfg['cost_axes'] else ('policy', cfg['policy_axes'])
    name, choices = next(iter(axes.items()))
    actual_group = 'move_profile' if name.startswith('gpr_') else group
    value = next(v for v in choices if v != (anchor[actual_group][name][0]
                 if isinstance(anchor[actual_group][name], list) else anchor[actual_group][name]))
    alternative[actual_group][name] = [value,value] if isinstance(anchor[actual_group][name], list) else value
    cfg['adaptive_seeds'] = [anchor, alternative]
    api = AdaptiveProposals(cfg)
    tested = {pressure_proposals.profile_identity(h['proposal']) for r in reviews if r['benchmarks'] == [target]
              for h in r['observations'] if 'proposal' in h}
    cfg['reserved_profile_ids'] = sorted(tested - {api.identity(anchor)})
    seed_count = 2 if deadline else 3
    def validate(value):
        if not isinstance(value, dict) or value.keys() != {'hypothesis','seeds'} or not isinstance(value['hypothesis'], str) or not value['hypothesis'].strip() or len(value['hypothesis']) > 8000:
            raise ValueError('planner must return hypothesis and three complete seeds')
        if not isinstance(value['seeds'], list) or len(value['seeds']) != seed_count:
            raise ValueError('planner requires '+str(seed_count)+' tests')
        seeds = [api.project(p['knobs'],p['rationale']) if isinstance(p,dict) and p.keys()=={'knobs','rationale'}
                 else api.validate(p) for p in value['seeds']]
        keys = [api.identity(p) for p in seeds]
        if len(set(keys)) != seed_count or any(k in tested or k == api.identity(anchor) for k in keys):
            raise ValueError('planner repeats an existing or control profile')
        return {**value,'seeds':seeds}
    prompt = {'task': 'Design '+str(seed_count)+' meaningful BOOM compiler experiments for '+target,
        'family': family, 'hypothesis': cfg['hypothesis'], 'microarchitecture': MICROARCH,
        'cost_axes': cfg['cost_axes'], 'policy_axes': cfg['policy_axes'], 'example_profile': anchor,
        'train_reviews': cfg['analysis_evidence']['recent_train_reviews'],
        'constraints': 'JSON {hypothesis:string,seeds:['+str(seed_count)+' objects with knobs:{axis:value},rationale:string]}. '
            'Choose two informative ablations and one interaction when supported by evidence. '
            'Each rationale must describe a generated-code hypothesis and falsification. '
            'List only enumerated cost/policy axes in knobs; omitted values are copied from the immutable anchor. '
            'Integer-mode costs use one integer for both modes. An unconfirmed faster profile never replaces the anchor automatically. '
            'No repeated profiles, commands, tools, '
            'source patches, flags, ISA/ABI changes or RVV. Source-derived capacities are not measured occupancy. '
            'Do not invent cycle bottlenecks or register parking. Scores from other targets/policies do not transfer. '
            'A generic microkernel proxy failed validation. Propose alternatives instead of endlessly refining one idea.'}
    if family in ('codegen-growth','structural-frontier'):
        seeds = []
        choices = FAMILIES[family]['policy_axes']['growth_budget']
        # Reserve two structural points for evidence-guided CLI feedback.
        for name in choices[:6] if family == 'structural-frontier' else choices:
            value = deepcopy(anchor)
            value['policy']['growth_budget'] = name
            value['rationale'] = FAMILIES[family]['hypothesis']+' Intervention: '+name+'. Compare the isolated changes and their interaction against the unchanged control.'
            if api.identity(value) not in tested and api.identity(value) != api.identity(anchor):
                seeds.append(value)
        if not seeds:
            fallback = {**(settings or {}), 'deadline_mode':True,
                'family_schedule':['integer-idioms','branch-growth','allocation-memory']}
            fallback['round_overrides'] = {k:v for k,v in fallback.get('round_overrides',{}).items()
                if k != str(len(reviews))}
            return plan(base,reviews,directory,fallback)
        proposal = {'hypothesis':cfg['hypothesis'],'seeds':seeds}
        budget = len(seeds) + (2 if family == 'structural-frontier' else 1)
        cfg.update(campaign_budget=budget,iterations=budget)
    else:
        for attempt in range(3):
            try:
                proposal = pressure_proposals.request_json(cfg, prompt, directory / f'planner-{attempt}', validate)
                break
            except (ValueError, TypeError) as exc:
                prompt['previous_validation_error'] = str(exc)
        else:
            raise ValueError('planner produced no valid new tests after three attempts')
    cfg['adaptive_seeds'] = [anchor, *proposal['seeds']]
    if deadline:
        cfg['prepare_seed_count'] = len(cfg['adaptive_seeds'])
    AdaptiveProposals(cfg)
    focused_campaign.validate_config(cfg)
    if source:
        focused_campaign.verify_incumbent_archive(cfg, read(cfg['hardware_manifest']))
    write(directory / 'decision.json', {'target':target, 'family':family,
        'hypothesis':proposal['hypothesis'], 'compiler_seed':selected['compiler']['compiler_id'],
        'source_confirmed_for_target':bool(source), 'reference_used_for_proposals':False})
    write(directory / 'config.json', cfg)
    return cfg


def reference_due(review, root, settings=None, now=None):
    """Use validation milestones without exposing reference scores to proposals."""
    if not review.get('selected') or not review.get('validated_selection'):
        return False
    key = '-'.join(review['benchmarks'])+'-'+review['selected']['compiler']['compiler_id']
    if (root / key / 'result.json').exists():
        existing = read(root / key / 'result.json')
        if not existing.get('complete') or existing.get('compiler_id') != review['selected']['compiler']['compiler_id'] or existing.get('benchmarks') != review['benchmarks']:
            raise ValueError('reference result identity or completion differs')
        return False
    if not settings or settings.get('reference_policy','always') == 'always':
        return True
    if settings['reference_policy'] != 'milestone':
        raise ValueError('unsupported reference policy')
    previous = [p for p in root.glob('*/result.json') if read(p).get('complete')]
    if not previous:
        return True
    score = review.get('confirmed_train_speedup') or review['selected'].get('speedup',1)
    elapsed = (time.time() if now is None else now)-max(p.stat().st_mtime for p in previous)
    return score >= settings.get('reference_min_speedup',1.05) and elapsed >= settings.get('reference_interval_hours',24)*3600


def reuse_prepared(config, reviews, destination):
    """Copy private preparation artifacts; prepare() revalidates bytes/native output."""
    api = AdaptiveProposals(config)
    copied = []
    for r in reversed(reviews):
        source = Path(r['source'])
        old = read(source / 'config.json')
        fields = ('benchmarks','gcc_root','baseline_prefix','hardware_manifest','small_images')
        if any(old.get(k) != config.get(k) for k in fields):
            continue
        mapping = [('baseline-prepared', source / 'baseline-prepared')]
        for index, seed in enumerate(api.seed_profiles()):
            for row in r['observations']:
                if row.get('proposal') and pressure_proposals.profile_identity(row['proposal']) == api.identity(seed):
                    mapping.append((f'candidate-{index:03d}', source / f"candidate-{row['index']:03d}"))
        for name, src in mapping:
            dest = destination / name
            if dest.exists() or not (src / 'prepared.json').exists():
                continue
            record = read(src / 'prepared.json')
            if digest(src / 'train/workload.tar.gz') != record['archive_sha256']:
                raise ValueError('archived preparation bytes changed')
            # Ordinary copies: later native revalidation must not mutate history.
            shutil.copytree(src, dest)
            copied.append({'source':str(src),'destination':str(dest)})
    write(destination.parent / 'preparation-reuse.json', copied)


def dispatch_ready(config):
    """Read-only connectivity/idle check; the child repeats full cloud/hardware policy checks."""
    subprocess.run(['aws','--profile',config['aws_profile'],'--region',config['region'],
        'ec2','describe-instances','--instance-ids',*[w['instance_id'] for w in config['fpga_workers']],
        '--query','Reservations[].Instances[].State.Name','--output','json','--no-cli-pager',
        '--cli-connect-timeout','5','--cli-read-timeout','10'],check=True,capture_output=True,text=True,timeout=60)
    for worker in config['fpga_workers']:
        result = subprocess.run(['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',
            '-o','ConnectTimeout=10',worker['ssh_alias'],'pgrep -x FireSim-f2'],capture_output=True,timeout=20)
        if result.returncode != 1:
            raise RuntimeError('driver occupied or idle state unverifiable: '+worker['ssh_alias'])


def pending_cache_probe(settings):
    """Run a prepared diagnostic once at a drained campaign boundary."""
    spec = (settings or {}).get('cache_probe')
    if spec is None:
        return None
    required = {'config', 'prepared_directory', 'result_directory'}
    if not isinstance(spec, dict) or not required <= spec.keys() or spec.keys() - required - {'failure_policy'} or any(
            not isinstance(spec[k], str) or not spec[k] for k in required) or spec.get('failure_policy','stop') not in ('stop','quarantine'):
        raise ValueError('cache_probe requires config, prepared_directory and result_directory')
    destination = Path(spec['result_directory'])
    if (destination / 'quarantined.json').exists():
        if spec.get('failure_policy') == 'quarantine':
            return None
        raise RuntimeError('cache diagnostic quarantined; inspect it before continuing')
    if (destination / 'result.json').exists():
        if not read(destination / 'result.json').get('success'):
            if spec.get('failure_policy') == 'quarantine':
                return None
            raise RuntimeError('cache diagnostic failed; inspect it before continuing')
        return None
    prepared = Path(spec['prepared_directory'])
    if not (prepared / 'correctness.json').exists():
        return None  # Keep ordinary experiments running while QEMU prepares.
    if not read(prepared / 'correctness.json').get('success') or read(prepared / 'build.json').get('suite') != 'cache':
        raise ValueError('cache diagnostic requires a successful prepared cache suite')
    return spec


def check_cache_probe_completion(spec, error=None):
    """Reject diagnostic scores; optionally quarantine this job and keep the core loop usable."""
    destination = Path(spec['result_directory'])
    result = destination / 'result.json'
    if error is None and result.exists() and read(result).get('success'):
        return True
    if spec.get('failure_policy') != 'quarantine':
        raise RuntimeError('cache diagnostic did not complete correctly')
    write(destination / 'quarantined.json', {'success': False, 'accepted_hardware_score': False,
        'reason': str(error or 'diagnostic completion/correctness gate failed'),
        'next_action': 'Preserve failure; ordinary workload dispatch must repeat idle/cloud/hardware checks.'})
    return False


def supervise(initial, root, poll=30, settings=None, resume_run=None):
    """Wait for the existing run, then keep launching reviewed rounds until stopped."""
    stop = root / 'STOP'
    state_path = root / 'state.json'
    state = read(state_path) if state_path.exists() else {'reviews':[], 'current':str(initial), 'phase':'waiting'}
    if resume_run is not None:
        if not controller_idle(resume_run) or (resume_run / 'result.json').exists():
            raise ValueError('resume run is active or already complete; preserve it')
        state['current'] = str(resume_run)
        for name in ('failure','blocker','child_pid','owned_pids','active','completed_profiles'):
            state.pop(name,None)
    stopping = False
    def request_stop(*_):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    base = read(initial / 'config.json')
    if settings:
        if settings.get('llm_model'):
            base['model'] = settings['llm_model']
        if settings.get('llm_effort'):
            base['llm_effort'] = settings['llm_effort']
    if not state['reviews']:
        archives = ([base['incumbent_run']] if base.get('incumbent_run') else []) + [
            item['run_dir'] for item in base.get('incumbent_supporting_runs', [])]
        state['reviews'] = [review(Path(p)) for p in dict.fromkeys(archives)]
    child = None
    def publish(phase, **values):
        state.update(phase=phase, updated_at=time.time(), **values)
        write(state_path, state)
        print(json.dumps({'phase':phase, **values}),flush=True)
    def stopped():
        return stopping or stop.exists() or any(Path(p).exists() for p in (settings or {}).get('external_stop_controls',[]))
    def execute(commands, directory, phase, index):
        """Track owned process groups; on stop drain all before returning."""
        handles = []
        try:
            for label, command in commands:
                log = (directory / (label + '.log')).open('a')
                process = subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                handles.append((process,log))
            publish(phase,round=index, owned_pids=[p.pid for p,_ in handles])
            while any(p.poll() is None for p,_ in handles):
                failed = any(p.poll() not in (None,0) for p,_ in handles)
                if stopped() or failed:
                    for process,_ in handles:
                        if process.poll() is None:
                            os.killpg(process.pid,signal.SIGINT)
                    for process,_ in handles:
                        process.wait()
                    break
                time.sleep(poll)
            if any(p.wait() for p,_ in handles) and not stopped():
                raise RuntimeError('owned preparation/reference process failed; inspect logs before dispatch')
        finally:
            for process,log in handles:
                if process.poll() is None:
                    os.killpg(process.pid,signal.SIGINT)
                    process.wait()
                log.close()
    def launch(cfg,directory,run,index):
        nonlocal child
        command = [sys.executable,'-u','-m','examples.boom_cost_model.focused_campaign',
                   '--config',str(directory / 'config.json'),'--run-dir',str(run)]
        write(directory / 'launch.json',{'command':command,'source_sha256':digest(__file__),
            'authorization':'User explicitly authorized continuous loops until stopped, November 2, 2026.'})
        with (directory / 'campaign.log').open('a') as log:
            child = subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            state['current'] = str(run)
            publish('running',round=index,child_pid=child.pid,log=str(directory / 'campaign.log'))
            while child.poll() is None:
                if stopped():
                    os.killpg(child.pid,signal.SIGINT)
                    publish('draining',round=index)
                    child.wait()
                    break
                time.sleep(poll)
            code = child.wait()
            child = None
        if code and not stopped():
            raise RuntimeError(f'round {index} failed with exit {code}; inspect logs/drivers before resuming')
    try:
        publish('waiting',current=state['current'])
        if resume_run is not None:
            cfg = read(resume_run.parent / 'config.json')
            focused_campaign.validate_config(cfg)
            focused_campaign.proposal_api(cfg)
            if settings and any(cfg.get(field) != settings[setting] for field,setting in
                    [('model','llm_model'),('llm_effort','llm_effort')] if settings.get(setting)):
                raise ValueError('resumed LLM configuration differs from requested policy; clone into a fresh run')
            if (resume_run / 'config.json').exists() and read(resume_run / 'config.json') != cfg:
                raise ValueError('resume configuration differs from its immutable snapshot')
            while not stopped():
                try:
                    dispatch_ready(cfg)
                    break
                except (subprocess.SubprocessError,RuntimeError) as exc:
                    publish('waiting-for-preflight',blocker=str(exc))
                    time.sleep(poll)
            if not stopped():
                launch(cfg,resume_run.parent,resume_run,len(state['reviews']))
        while not stopped():
            source = Path(state['current'])
            if not controller_idle(source):
                if (source / 'progress.json').exists():
                    progress = read(source / 'progress.json')
                    state.update(updated_at=time.time(),active=progress.get('active'),
                                 completed_profiles=len(progress.get('history', [])))
                    write(state_path,state)
                time.sleep(poll)
                continue
            if not (source / 'result.json').exists():
                raise RuntimeError('previous controller exited without result.json; inspect it before any dispatch')
            if not any(r['source'] == str(source.resolve()) for r in state['reviews']):
                state['reviews'].append(review(source))
                latest = state['reviews'][-1]
                publish('reviewed',last_review={'source':latest['source'],
                    'benchmarks':latest['benchmarks'], 'incumbent_retained':latest['incumbent_retained'],
                    'selected_train_times':latest['selected'].get('train_times') if latest.get('selected') else None})
            diagnostic = pending_cache_probe(settings)
            if diagnostic:
                while not stopped():
                    try:
                        dispatch_ready(read(diagnostic['config']))
                        break
                    except (subprocess.SubprocessError, RuntimeError) as exc:
                        publish('waiting-for-preflight', blocker=str(exc))
                        time.sleep(poll)
                if stopped():
                    break
                destination = Path(diagnostic['result_directory'])
                error = None
                try:
                    execute([('cache-probe', [sys.executable, '-u', '-m',
                        'examples.boom_cost_model.run_probes', '--config', diagnostic['config'],
                        '--probe-run-dir', diagnostic['prepared_directory'], '--run-dir', str(destination)])],
                        root, 'cache-diagnostic', len(state['reviews']))
                except RuntimeError as exc:
                    error = exc
                if stopped():
                    break
                if not check_cache_probe_completion(diagnostic, error):
                    publish('cache-diagnostic-quarantined', diagnostic=str(destination),
                        inspect_drivers_before_resume=True)
            index = len(state['reviews'])
            if shutil.disk_usage(root).free < 20 * 1024**3:
                raise RuntimeError('less than 20 GiB free at '+str(root)+'; preserve results and resolve space before dispatch')
            directory = root / f'round-{index:03d}'
            directory.mkdir(exist_ok=True)
            if not (directory / 'config.json').exists():
                publish('planning', round=index)
                cfg = plan(base, state['reviews'], directory,settings) if settings else plan(base,state['reviews'],directory)
            else:
                cfg = read(directory / 'config.json')
            if settings and any(cfg.get(field) != settings[setting] for field,setting in
                    [('model','llm_model'),('llm_effort','llm_effort')] if settings.get(setting)):
                raise ValueError('queued LLM configuration differs from requested policy; preserve it and clone into a fresh run')
            run = directory / 'run'
            reuse_prepared(cfg,state['reviews'],run)
            while not stopped():
                try:
                    dispatch_ready(cfg)
                    break
                except (subprocess.SubprocessError, RuntimeError) as exc:
                    publish('waiting-for-preflight', round=index, blocker=str(exc))
                    time.sleep(poll)
            if stopped():
                break
            # Validate each newly selected compiler on held-out reference inputs
            # while preparing the NEXT loop on CPU. Reference results never
            # enter plan(), train reviews, or the Claude feedback prompt.
            selected = state['reviews'][-1].get('selected')
            validation_root = Path((settings or {}).get('reference_root',root / 'reference-validation'))
            if reference_due(state['reviews'][-1],validation_root,settings):
                key = '-'.join(state['reviews'][-1]['benchmarks']) + '-' + selected['compiler']['compiler_id']
                validation = validation_root / key
                if not (validation / 'result.json').exists():
                    validation.mkdir(parents=True,exist_ok=True)
                    execute([
                        ('reference', [sys.executable,'-u','-m','examples.boom_cost_model.reference_check',
                            '--source',str(source),'--run-dir',str(validation),
                            *[arg for p in (settings or {}).get('reference_cache_dirs',[])
                                for arg in ('--baseline-cache',str(p))]]),
                        ('prepare-next', [sys.executable,'-u','-m','examples.boom_cost_model.focused_campaign',
                            '--config',str(directory / 'config.json'),'--run-dir',str(run),'--prepare-only'])],
                        directory,'reference-and-next-preparation',index)
                    if stopped():
                        break
                    if not (validation / 'result.json').exists():
                        raise RuntimeError('reference validation did not complete; no new dispatch')
                    publish('reference-validated',reference_result=str(validation / 'result.json'))
                dispatch_ready(cfg)
            launch(cfg,directory,run,index)
            if stopped():
                break
        publish('stopped', stop_requested=True)
    except Exception:
        if child is not None and child.poll() is None:
            os.killpg(child.pid,signal.SIGINT)
            child.wait()
        publish('blocked', failure=traceback.format_exc(), inspect_drivers_before_resume=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--initial-run',type=Path,required=True)
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--settings',type=Path)
    parser.add_argument('--resume-run',type=Path,help='Explicitly resume a prepared, inspected run, retaining supervisor ownership')
    args = parser.parse_args()
    os.umask(0o077)
    args.directory.mkdir(parents=True,exist_ok=True)
    with (args.directory / 'supervisor.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
        settings = read(args.settings) if args.settings else None
        supervise(args.initial_run.resolve(), args.directory.resolve(),settings=settings,
                  resume_run=args.resume_run.resolve() if args.resume_run else None)


if __name__ == '__main__':
    main()
