"""Bounded Saturn producer/consumer campaign with fresh paired controls.

Adapters prepare an immutable bundle and measure it on the admitted physical
worker. CHIA tasks may implement these callables. This controller owns ordering,
selection and persistence; adapters own image construction and native correctness.
Measurements are never reused from historical caches.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import fcntl
import hashlib
import json
from pathlib import Path
import statistics
import threading
import uuid

from chia.chipyard.measurements import measurement_key


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


@dataclass(frozen=True)
class Policy:
    worker_id: str
    platform_sha256: str
    hardware: dict
    runtime_sha256: str
    scope: str = 'train'
    confirm_repeats: int = 3
    min_improvement: float = 0.02
    final_ref: bool = True

    def validate(self):
        if self.scope not in ('test', 'train') or not 1 <= self.confirm_repeats <= 5:
            raise ValueError('invalid search scope or confirmation count')
        if not 0 <= self.min_improvement <= 0.1 or not self.worker_id:
            raise ValueError('invalid threshold or physical worker')


def validate_receipt(receipt, artifact, request, policy):
    identity = receipt.get('identity', {})
    expected = dict(worker_id=policy.worker_id, platform_sha256=policy.platform_sha256,
                    bundle_sha256=artifact['bundle_sha256'], input_id=artifact['input_id'],
                    role=artifact['role'], sample=request['sample'], phase=request['phase'])
    if receipt.get('status') != 'correct' or receipt.get('backend') != 'fpga':
        raise ValueError('hardware/native correctness receipt required')
    if any(identity.get(key) != value for key, value in expected.items()):
        raise ValueError('paired receipt identity mismatch')
    if receipt.get('executable_sha256') != artifact['executable_sha256']:
        raise ValueError('paired receipt executable mismatch')
    cycles = receipt.get('whole_boot_simulation_cycles')
    if type(cycles) is not int or cycles <= 0:
        raise ValueError('positive target cycle count required')
    return cycles


def run(root: Path, proposals: list[dict], policy: Policy, prepare, measure,
        stop: threading.Event | None = None):
    """Execute a bounded campaign.

    prepare(proposal-or-None, scope, directory) returns an immutable artifact
    containing role, scope, bundle_sha256, executable_sha256, input_id,
    workload_sha256 (input/reference bytes plus invocation identity) and
    fingerprint. measure(artifact, request, directory) returns the admitted
    collector's receipt. Each request carries a fresh sample ID and phase.
    Setting stop drains current preparation/measurement and prevents new work.
    """
    policy.validate()
    if not 1 <= len(proposals) <= 12:
        raise ValueError('campaign requires 1..12 bounded proposals')
    root = Path(root)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    stop = stop or threading.Event()
    with (root / 'campaign.lock').open('a') as lease:
        try:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('another paired campaign owns this directory') from exc
        return _run(root, proposals, policy, prepare, measure, stop)


def _run(root, proposals, policy, prepare, measure, stop):
    state_path = root / 'progress.json'
    identity = digest({'policy': policy.__dict__, 'proposals': proposals})
    if state_path.exists():
        state = json.loads(state_path.read_text())
        if state['campaign_sha256'] != identity:
            raise ValueError('campaign configuration changed')
        # Never re-dispatch an interrupted physical task. The persisted active
        # entry identifies the task whose private receipt must be recovered.
        if state.get('active') or state.get('status') != 'complete':
            raise RuntimeError('interrupted campaign requires receipt recovery before resume')
        for sample in state['samples']:
            receipt = json.loads((root / sample['receipt']).read_text())
            if digest(receipt) != sample['receipt_sha256']:
                raise ValueError('saved campaign receipt changed')
        return state
    state = {'campaign_sha256': identity, 'status': 'running', 'active': None,
             'scope': policy.scope, 'result_scope': 'screening' if policy.scope == 'test' else 'train optimization',
             'history': [], 'samples': [], 'winner': None, 'paired_controls': True}
    save(state_path, state)

    def prepared(proposal, scope, directory):
        artifact = prepare(proposal, scope, directory)
        role = '2-generic-vector' if proposal is None else '3-saturn-aware'
        if artifact.get('role') != role or artifact.get('scope') != scope:
            raise ValueError('prepared role/input scope mismatch')
        for key in ('bundle_sha256', 'executable_sha256', 'input_id', 'workload_sha256', 'fingerprint'):
            if not artifact.get(key):
                raise ValueError('incomplete prepared artifact')
        return artifact

    def sample(artifact, phase, order):
        number = len(state['samples'])
        request = {'sample': number, 'phase': phase, 'scope': artifact['scope'],
                   'order': order, 'attempt_id': uuid.uuid4().hex}
        key = measurement_key(artifact['fingerprint'], policy.hardware,
            policy.runtime_sha256, policy.worker_id, artifact['scope'] + ':' + artifact['input_id'], number)
        request['measurement_key'] = key
        directory = root / f'sample-{number:04d}'
        directory.mkdir(mode=0o700)
        state['active'] = {'request': request, 'artifact': artifact, 'directory': directory.name}
        save(state_path, state)
        receipt = measure(artifact, request, directory)
        cycles = validate_receipt(receipt, artifact, request, policy)
        save(directory / 'receipt.json', receipt)
        state['samples'].append({'measurement_key': key, 'request': request,
            'cycles': cycles, 'role': artifact['role'], 'receipt': directory.name + '/receipt.json',
            'receipt_sha256': digest(receipt)})
        state['active'] = None
        save(state_path, state)
        return cycles

    def pair(baseline, candidate, phase, reverse=False):
        if baseline['input_id'] != candidate['input_id']:
            raise ValueError('paired input mismatch')
        if baseline.get('workload_sha256') != candidate.get('workload_sha256'):
            raise ValueError('paired invocation or input/reference bytes differ')
        values = {}
        for order, (name, artifact) in enumerate((('candidate', candidate), ('baseline', baseline))
                if reverse else (('baseline', baseline), ('candidate', candidate))):
            if stop.is_set():
                raise InterruptedError('draining campaign stop requested')
            values[name] = sample(artifact, phase, order)
        return 1 - values['candidate'] / values['baseline']

    try:
        if stop.is_set():
            raise InterruptedError('campaign stop requested before preparation')
        baseline = prepared(None, policy.scope, root / 'baseline')
        if stop.is_set():
            raise InterruptedError('campaign stop requested after baseline preparation')
        seen = {baseline['executable_sha256']}
        with ThreadPoolExecutor(max_workers=1) as producer:
            pending = producer.submit(prepared, proposals[0], policy.scope, root / 'candidate-000')
            best = None
            for index, proposal in enumerate(proposals):
                candidate = pending.result()
                if stop.is_set():
                    raise InterruptedError('draining campaign stop requested')
                if index + 1 < len(proposals):
                    pending = producer.submit(prepared, proposals[index + 1], policy.scope,
                                              root / f'candidate-{index + 1:03d}')
                record = {'proposal': proposal, 'candidate': candidate}
                if candidate['executable_sha256'] in seen:
                    record['status'] = 'duplicate executable'
                else:
                    seen.add(candidate['executable_sha256'])
                    improvement = pair(baseline, candidate, 'search', reverse=bool(index % 2))
                    record.update(status='measured', pilot_improvement=improvement)
                    if improvement >= policy.min_improvement:
                        repeats = [pair(baseline, candidate, 'confirmation', reverse=bool((index + n + 1) % 2))
                                   for n in range(policy.confirm_repeats)]
                        confirmed = statistics.median(repeats)
                        record.update(confirmation_improvements=repeats, confirmed_improvement=confirmed,
                                      accepted=confirmed >= policy.min_improvement)
                        if record['accepted'] and (best is None or confirmed > best[0]):
                            best = (confirmed, proposal, candidate)
                state['history'].append(record)
                save(state_path, state)
            if best:
                state['winner'] = best[1]
                if policy.final_ref:
                    ref_base = prepared(None, 'ref', root / 'ref-baseline')
                    ref_candidate = prepared(best[1], 'ref', root / 'ref-winner')
                    state['holdout_improvement'] = pair(ref_base, ref_candidate, 'holdout')
                    state['holdout_correctness_passed'] = True
                    state['holdout_improvement_claim'] = state['holdout_improvement'] >= policy.min_improvement
            state['status'] = 'complete'
    except InterruptedError:
        state['status'] = 'drained'
    except BaseException as exc:
        state.update(status='blocked', failure=str(exc))
        save(state_path, state)
        raise
    save(state_path, state)
    return state
