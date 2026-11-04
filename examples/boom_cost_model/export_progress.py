"""Publish completed follow-up measurements using an explicit data allowlist."""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import re

from chia.chipyard.boom_model import validate_policy
from examples.boom_cost_model.export_research import BASELINE, read, spec_samples, proposal_data


def trial(record):
    result = proposal_data(record)
    policy = record.get('proposal', {}).get('policy')
    if policy is not None:
        result['policy'] = validate_policy(policy)
    result['skipped_duplicate_code'] = 'skipped' in record
    result['failed_or_rejected'] = not bool(record.get('success')) and 'skipped' not in record
    return result


def export(run_root, compiler_root, output):
    state = read(run_root / 'boom-autopilot-fast-20261102/state.json')
    aliases = {}
    campaigns, samples, identities = [], [], {BASELINE}
    seen = set()
    for review in state['reviews']:
        root = Path(review['source']).resolve()
        root.relative_to(run_root.resolve())
        if root in seen:
            continue
        seen.add(root)
        result, cfg = read(root/'result.json'), read(root/'config.json')
        if not result.get('complete'):
            raise ValueError('only completed, reviewed campaigns may be exported')
        label = 'followup-' + str(len(campaigns)).zfill(2)
        for worker in cfg['fpga_workers']:
            aliases.setdefault(worker['instance_id'], 'worker-' + str(len(aliases)))
        history = [trial(row) for row in result['history']]
        identities.update(h['compiler_id'] for h in history if h['compiler_id'])
        samples.extend(spec_samples(root, label, aliases))
        campaigns.append({'id': label, 'family': cfg.get('hypothesis_family', cfg.get('campaign_kind')),
            'benchmarks': cfg['benchmarks'], 'model': cfg['model'],
            'effort': cfg.get('llm_effort', 'not-explicitly-pinned'),
            'complete': True, 'history': history,
            **{k:result.get(k) for k in ['baseline_retained', 'incumbent_retained',
                'train_confirmation_checked', 'confirmation_failed', 'confirmed_train_speedup',
                'confirmed_incremental_speedup', 'reference_checked']},
            'minimum_incremental_improvement': cfg.get('min_incremental_improvement'),
            'result_sha256': hashlib.sha256((root/'result.json').read_bytes()).hexdigest()})
    references = []
    for path in sorted((run_root/'boom-autopilot-20261102/reference-validation').glob('*/result.json')):
        result = read(path)
        if not result.get('complete') or not result.get('reference_checked'):
            continue
        identities.add(result['compiler_id'])
        rows = spec_samples(path.parent, 'heldout-' + str(len(references)), aliases)
        if not rows:
            raise ValueError('held-out result lacks saved successful native comparisons')
        samples.extend(rows)
        references.append({'compiler_id': result['compiler_id'], 'benchmarks': result['benchmarks'],
            'excluded_from_proposals': True, 'workers': [
                {'worker': aliases[w['instance_id']], 'order': w['order'],
                 'reference_speedup': w['reference_speedup'], 'samples': {
                    role: {'compiler_id': v['compiler']['compiler_id'], 'raw_times': v['raw_times'],
                           'native_correctness_passed': v['success']}
                    for role,v in w['samples'].items()}} for w in result['workers']]})
    models = {}
    allowed = {'compiler_id', 'gcc_revision', 'baseline_gcc_sha256', 'costs', 'scheduling',
        'tuning', 'model_version', 'move_profile', 'move_profile_version', 'policy',
        'policy_version', 'boom_revision', 'source_hashes', 'diff_sha256'}
    for identity in sorted(identities - {BASELINE}):
        if not re.fullmatch('[0-9a-f]{64}', identity):
            raise ValueError('invalid compiler identity')
        value = read(compiler_root/'boom-gcc/compilers'/identity/'cost-model.json')
        models[identity] = {k:v for k,v in value.items() if k in allowed}
    cache_study = {'status': 'corrected diagnostic prepared; hardware sensitivity not yet established',
        'working_set_KiB': [8,16,32,64,256,1024,4096,16384],
        'kernels': ['randomized dependent pointer chase','sequential line stream'],
        'purpose': 'Diagnostic workload qualification, not a compiler score or an application speedup.'}
    old_probe = run_root/'cache-study-20261103/f2/result.json'
    if old_probe.exists() and not read(old_probe).get('success'):
        cache_study['first_hardware_attempt'] = {'success':False, 'accepted_score':False,
            'failure':'8 KiB streaming sample reported zero elapsed nanoseconds; guest exited nonzero.',
            'corrective_action':'Calibrate timed batches to at least 1 ms and quarantine optional diagnostic failures.'}
    prepared = run_root/'cache-study-20261103/prepared-v2/correctness.json'
    if prepared.exists():
        correct = read(prepared)
        cache_study['corrected_QEMU'] = {'success':bool(correct.get('success')),
            'cases':len(correct.get('records',[])), 'FPGA_executed':False}
    data = {'snapshot_date': datetime.now(timezone.utc).date().isoformat(),
        'estimate': True, 'SPEC_reportable_score': False,
        'interpretation': 'Non-compliant partial-suite FPGA research estimates; train and held-out inputs are distinct. Reused observations are not independent measurements.',
        'campaigns': campaigns, 'samples': samples, 'heldout_validation': references, 'compiler_models': models,
        'cache_study': cache_study}
    output.mkdir(parents=True, exist_ok=True)
    filename = 'progress-20261103.json'
    encoded = (json.dumps(data, indent=2, allow_nan=False)+'\n').encode()
    (output/filename).write_bytes(encoded)
    manifest = read(output/'manifest.json')
    manifest['files'][filename] = hashlib.sha256(encoded).hexdigest()
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    return {'campaigns': len(campaigns), 'validated_observations': len(samples), 'models': len(models)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--compiler-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(export(args.run_root, args.compiler_root, args.output))


if __name__ == '__main__':
    main()
