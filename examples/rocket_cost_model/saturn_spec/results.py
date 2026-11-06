"""Fail-closed collection for a future native manager run, never a dispatcher."""

import json
import math
from pathlib import Path
import re

from examples.rocket_cost_model.rvv_gate.validate import validate as validate_probe
from .bundle import DRIVER_SHA, AGFI, read_json, regular_tree, sha
from .staging import verify_stage


def validate_completion(plan, image, completion, preflight):
    expected = {'backend': 'fpga', 'task': 'runworkload', 'returncode': 0, 'image_id': plan['image_id'],
                'worker_id': plan['identity']['worker_id'], 'worker_lease_held': True,
                'agfi': AGFI, 'driver_sha256': DRIVER_SHA, 'vlen_bits': 256,
                'phase': plan['identity']['phase'], 'sample': plan['identity']['sample']}
    if any(completion.get(k) != value or type(completion.get(k)) is not type(value)
           for k, value in expected.items()):
        raise ValueError('manager completion/target/worker identity mismatch')
    if preflight.get('platform_sha256') != plan['identity']['platform_sha256'] \
            or preflight.get('worker', {}).get('idle') is not True \
            or preflight['worker'].get('instance_id') != plan['identity']['worker_id'] \
            or preflight['worker'].get('agfi') != AGFI \
            or preflight['worker'].get('driver_sha256') != DRIVER_SHA:
        raise ValueError('wrong preflight identity')
    start, end, checked = completion.get('started_at'), completion.get('finished_at'), preflight.get('checked_at')
    if any(type(n) not in (int, float) or not math.isfinite(n) for n in (start, end, checked)) \
            or not checked <= start <= checked + 300 or end < start:
        raise ValueError('stale preflight or invalid manager timestamps')
    if image.get('image_id') != plan['image_id'] or image.get('runtime_sha256') != plan['runtime_sha256']:
        raise ValueError('stale image receipt')


def collect(stage, image_path, completion_path, preflight_path, collected, destination):
    stage = Path(stage)
    p = verify_stage(stage)
    if p['identity']['phase'] == 'diagnostic':
        raise ValueError('diagnostic runs cannot enter performance collection')
    image, completion, preflight = map(read_json, (image_path, completion_path, preflight_path))
    validate_completion(p, image, completion, preflight)
    for key, path in [('plan_sha256', stage / 'plan.json'), ('image_receipt_sha256', Path(image_path)),
                      ('preflight_sha256', Path(preflight_path))]:
        if completion.get(key) != sha(path):
            raise ValueError('completion refers to different execution artifacts')
    if image.get('plan_sha256') != sha(stage / 'plan.json'):
        raise ValueError('image receipt refers to different stage')
    for field in ('rootfs', 'bootbinary'):
        if sha(image[field]) != image[field + '_sha256']:
            raise ValueError('image artifact changed')
    root = Path(collected)
    regular_tree(root)
    result = root / 'result'
    def text(name):
        return (result / name).read_text()
    if text('job.status').strip() != '0' or text('collection.status').strip() != '0':
        raise ValueError('guest or collection failed')
    if read_json(result / 'identity.json') != p['identity']:
        raise ValueError('stale collected guest identity')
    m = read_json(stage / 'overlay/root/saturn-spec/bundle/manifest.json')
    actual_sha = text('executable.sha256').split()
    if not actual_sha or actual_sha[0] != m['files_sha256'][m['executable']]:
        raise ValueError('wrong guest SPEC executable')
    uart = (root / 'uartlog').read_text()
    probe_sha = p['overlay_sha256']['root/saturn-spec/rvv-probe']
    probe = validate_probe({'status': '0', 'result.txt': text('probe.txt'),
        'binary.sha256': text('probe.sha256'), 'cpuinfo.txt': text('cpuinfo.txt')}, probe_sha, uart, True)
    simulation = re.findall(r'\*\*\* PASSED \*\*\* after (\d+) cycles', uart)
    if len(simulation) != 1 or '*** FAILED ***' in uart or 'Kernel panic' in uart:
        raise ValueError('missing successful simulation completion')
    for name in {m['stdout'], m['stderr'], *m['expected_outputs']}:
        if not (result / 'outputs' / name).is_file():
            raise ValueError('incomplete collected stdout/stderr/output files')
    for dest, source in m['expected_outputs'].items():
        if sha(result / 'outputs' / dest) != m['files_sha256'][source]:
            raise ValueError('SPEC exact expected-output mismatch')
    times = {}
    for key in ('real', 'user', 'sys'):
        values = re.findall(r'^' + key + r'\s+([0-9]+(?:\.[0-9]+)?)\s*$', text('time.txt'), re.M)
        if len(values) != 1:
            raise ValueError('invalid POSIX timing collection')
        times[key] = float(values[0])
    if not all(math.isfinite(n) and n >= 0 for n in times.values()) or times['real'] <= 0:
        raise ValueError('nonpositive or nonfinite guest elapsed time')
    evidence = {'schema_version': 1, 'status': 'correct', 'backend': 'fpga',
                'identity': p['identity'], 'image_id': p['image_id'], 'probe': probe,
                'target_guest_elapsed_seconds': times['real'], 'raw_posix_seconds': times,
                'whole_boot_simulation_cycles': int(simulation[0]),
                'timing_scope': 'guest process including startup and IO; cycles include boot',
                'collected_sha256': {n: sha(root / n) for n in sorted(regular_tree(root))},
                'image_receipt_sha256': sha(image_path), 'completion_sha256': sha(completion_path)}
    dest = Path(destination)
    dest.mkdir(parents=True, mode=0o700, exist_ok=False)
    (dest / 'result.json').write_text(json.dumps(evidence, indent=2) + '\n')
    return evidence
