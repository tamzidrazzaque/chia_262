"""Bounded adaptive SPEC loop using CHIA compiler/proposal tasks and Saturn F2.

Private configuration supplies existing compiler paths and the admitted manager.
Only validated cost JSON is model-generated. Native output gates and paired
controls remain in the existing manager lane. No historical timing is reused.
"""

from concurrent.futures import ThreadPoolExecutor
import argparse
import fcntl
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import tarfile
import uuid
import tempfile
import signal
import threading
import hashlib

from examples.rocket_cost_model.saturn_feedback_proposer import (
    publish_json, profile_signature, measured_history, codex_proposal)
from examples.rocket_cost_model.vector_cost_model import BASE_COSTS, proposal as validate


def ssh(config, command, **kwargs):
    return subprocess.run(['ssh', '-T', '-i', config['manager_key'], '-o', 'BatchMode=yes',
        '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=15', config['manager_host'],
        'bash --noprofile --norc -c ' + shlex.quote(command)], check=True, **kwargs)


def measure(config, selected, artifact, directory, index=0):
    """Transfer hash-bound bytes to the existing manager and obtain paired data."""
    remote = config['remote_root'].rstrip('/') + '/' + uuid.uuid4().hex
    request = {key: config[key] for key in ('address', 'task_root', 'policy', 'baseline')}
    request['policy'] = {**config['policy'], 'order_offset': index,
                        'sample_offset': config.get('first_id', 100) * 1000 + index * 100}
    request.update(proposal=selected, artifact={
        'archive_sha256': artifact.archive_sha256, 'manifest_sha256': artifact.manifest_sha256,
        'executable_sha256': artifact.executable_sha256})
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode='w:') as archive:
        for name, data in [('artifact.tar', artifact.archive),
                           ('request.json', json.dumps(request).encode())]:
            member = tarfile.TarInfo(name)
            member.mode = 0o600
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    publish_json(directory / 'dispatch.json', {'remote_run': remote, 'proposal': selected,
        'bundle_sha256': artifact.manifest_sha256, 'executable_sha256': artifact.executable_sha256})
    ssh(config, 'mkdir -m 700 -p ' + shlex.quote(config['remote_root']) +
        ' && mkdir -m 700 ' + shlex.quote(remote) + ' && tar -xf - -C ' + shlex.quote(remote),
        input=payload.getvalue(), stdout=subprocess.DEVNULL)
    command = ('cd ' + shlex.quote(config['manager_repo']) + ' && PYTHONPATH=' +
        shlex.quote(config['manager_repo']) + ' ' + shlex.quote(config['manager_python']) +
        ' -m examples.rocket_cost_model.saturn_adaptive_measure --incoming ' + shlex.quote(remote))
    with (directory / 'manager.log').open('wb') as log:
        ssh(config, command, stdout=log, stderr=subprocess.STDOUT)
    marker = 'SATURN_FEEDBACK_' + uuid.uuid4().hex
    output = ssh(config, "printf '%s\n' " + shlex.quote(marker) + '; cat ' +
        shlex.quote(remote + '/feedback.json'), capture_output=True, text=True).stdout
    if output.count(marker + '\n') != 1:
        raise ValueError('invalid manager feedback transfer')
    result = json.loads(output.split(marker + '\n', 1)[1])
    validate_feedback(result, selected, artifact, config)
    publish_json(directory / 'paired-feedback.json', result)
    return result


def validate_feedback(result, selected, artifact, config):
    """Bind the returned campaign to the submitted compiler and physical worker."""
    if result.get('campaign_status') != 'complete' or result.get('proposal') != selected:
        raise ValueError('manager campaign/proposal mismatch')
    expected = {'archive_sha256': artifact.archive_sha256, 'manifest_sha256': artifact.manifest_sha256,
                'executable_sha256': artifact.executable_sha256}
    if result.get('artifact') != expected:
        raise ValueError('manager feedback artifact mismatch')
    for field in ('worker_id', 'platform_sha256'):
        if result.get(field) != config['policy'][field]:
            raise ValueError('manager feedback physical target mismatch')
    for record in result.get('feedback', {}).get('candidates', []):
        if record.get('candidate_id') != selected['candidate_id'] or \
                profile_signature(record['proposal']['changes']) != profile_signature(selected['changes']):
            raise ValueError('manager feedback cost profile mismatch')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--preflight-only', action='store_true')
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    budget = config.get('candidate_budget', 6)
    if type(budget) is not int or not 1 <= budget <= 12:
        raise ValueError('candidate budget must be 1..12')
    if config['policy'].get('final_ref') or config['policy']['scope'] != 'test':
        raise ValueError('adaptive deployment currently requires explicit test screening with final_ref=false')
    args.out.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (args.out / 'loop.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (args.out / 'state.json').exists():
            raise RuntimeError('existing adaptive attempt requires evidence recovery; use its status')
        stop = threading.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: stop.set())
        run(config, args.out, budget, args.preflight_only, stop)


def run(config, out, budget, preflight_only=False, stop=None):
    stop = stop or threading.Event()
    import ray
    from chia.base.ChiaFunction import ChiaFunction, get
    from examples.rocket_cost_model.saturn_chia_tasks import prepare_artifact, await_task
    # The local existing runtime hosts compiler and credential tasks. Manager
    # artifact/F2 tasks run on its separately admitted private Ray instance.
    environment = {**config['compiler_env'], 'PYTHONPATH': str(Path(__file__).resolve().parents[2])}
    for key, value in config['compiler_env'].items():
        if key not in ('SATURN_BUILD_JOBS', 'SATURN_SHARED_COMPILER') and not Path(value).exists():
            raise ValueError('missing configured compiler path: ' + key)
    ray.init(num_cpus=config.get('cpus', 8), resources={'riscv_build': 1, 'codex_creds': 1},
        include_dashboard=False, runtime_env={'env_vars': environment},
        _temp_dir=tempfile.mkdtemp(prefix='saturn-adaptive-ray-'))
    @ChiaFunction(resources={'codex_creds': 1}, max_retries=0)
    def suggest(payload):
        return codex_proposal(payload)

    @ChiaFunction(resources={'riscv_build': 1}, max_retries=0)
    def admit_compiler():
        from examples.rocket_cost_model.vector_cost_model import build_environment
        evidence = build_environment()
        baseline = Path(os.environ['SATURN_BASELINE_PREFIX'])
        for executable in (baseline / 'bin/riscv64-unknown-linux-gnu-gcc',
                           Path(os.environ['SATURN_QEMU'])):
            subprocess.run([str(executable), '--version'], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for path in (Path(os.environ['SATURN_SPEC_DIR']) / 'bin/runcpu',
                     Path(os.environ['SATURN_SPECKLE']) / 'riscv.cfg'):
            if not path.is_file():
                raise ValueError('missing installed SPEC harness/configuration')
        return evidence

    state = {'status': 'preflight', 'budget': budget, 'candidates': [], 'incumbent': None,
             'baseline': config.get('initial_feedback', {}).get('baseline', {})}
    publish_json(out / 'state.json', state)
    try:
        # Exercise imports, executables, SSH and authentication before compiling.
        for name in ('gcc', 'g++', 'make', 'flex', 'bison', 'file'):
            subprocess.run([name, '--version'], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(['codex', 'login', 'status'], check=True, stdout=subprocess.DEVNULL)
        ssh(config, 'test -x ' + shlex.quote(config['manager_python']) +
            ' && test -d ' + shlex.quote(config['baseline']['bundles'][config['policy']['scope']]),
            stdout=subprocess.DEVNULL)
        publish_json(out / 'compiler-admission.json', await_task(admit_compiler.chia_remote(), 60))
        queue = [validate(item) for item in config['seeds']]
        signatures = {profile_signature(item['changes']) for item in queue}
        seen_elves = set(config.get('seen_executables', []))
        feedback = list(config.get('initial_feedback', {}).get('candidates', []))
        signatures.update(profile_signature(item['proposal']['changes']) for item in feedback
                          if item.get('proposal', {}).get('changes'))
        payload = {'goal': 'Reduce Saturn MCF cycles with bounded GCC vector costs',
            'allowed_fields': sorted(BASE_COSTS), 'cost_bounds': [1, 64],
            'measured_history': measured_history({'candidates': feedback}),
            'already_proposed': [json.loads(s) for s in sorted(signatures)]}
        evidence_sha = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        if config.get('proposal_admission'):
            admission = json.loads(Path(config['proposal_admission']).read_text())
            if admission.get('evidence_sha256') != evidence_sha or admission.get('status') != 'passed':
                raise ValueError('proposal admission does not match current measured history')
            admitted = validate(admission['proposal'])
        else:
            admitted = validate(await_task(suggest.chia_remote(payload), 600))
        signature = profile_signature(admitted['changes'])
        if signature in signatures:
            raise ValueError('preflight agent repeated an existing effective cost profile')
        signatures.add(signature)
        queue.append(admitted)
        publish_json(out / 'admitted-proposal.json', {
            'status': 'passed', 'evidence_sha256': evidence_sha, 'proposal': admitted})
        if preflight_only:
            state['status'] = 'preflight_passed'
            publish_json(out / 'state.json', state)
            return
        state['status'] = 'running'
        with ThreadPoolExecutor(max_workers=1) as producer:
            pending = None
            for index in range(budget):
                if stop.is_set():
                    state['status'] = 'drained'
                    publish_json(out / 'state.json', state)
                    return
                if not queue:
                    payload = {'goal': 'Reduce Saturn MCF cycles with bounded GCC vector costs',
                        'allowed_fields': sorted(BASE_COSTS), 'cost_bounds': [1, 64],
                        'measured_history': measured_history({'candidates': feedback}),
                        'already_proposed': [json.loads(s) for s in sorted(signatures)]}
                    selected = validate(await_task(suggest.chia_remote(payload), 600))
                    signature = profile_signature(selected['changes'])
                    if signature in signatures:
                        raise ValueError('feedback agent repeated effective cost profile')
                    signatures.add(signature)
                    queue.append(selected)
                selected = queue.pop(0)
                candidate_id = '3.' + str(config.get('first_id', 100) + index)
                selected = {'candidate_id': candidate_id, **selected}
                directory = out / candidate_id
                directory.mkdir(mode=0o700)
                record = {'candidate_id': candidate_id, 'proposal': selected, 'status': 'preparing'}
                state['candidates'].append(record)
                publish_json(out / 'state.json', state)
                if pending is None:
                    ref = prepare_artifact.chia_remote(candidate_id, selected)
                    artifact = await_task(ref, 14400)
                else:
                    artifact = pending.result()
                    pending = None
                # Prepare the next seed while F2 measures this candidate.
                if queue and index + 1 < budget:
                    next_id = '3.' + str(config.get('first_id', 100) + index + 1)
                    next_proposal = {'candidate_id': next_id, **queue[0]}
                    pending = producer.submit(lambda cid=next_id, p=next_proposal:
                        await_task(prepare_artifact.chia_remote(cid, p), 14400))
                record['executable_sha256'] = artifact.executable_sha256
                record['bundle_sha256'] = artifact.manifest_sha256
                if stop.is_set():
                    record['status'] = 'prepared'
                    state['status'] = 'drained'
                    publish_json(out / 'state.json', state)
                    return
                if artifact.executable_sha256 in seen_elves:
                    record['status'] = 'duplicate executable'
                else:
                    record['status'] = 'measuring'
                    publish_json(out / 'state.json', state)
                    result = measure(config, selected, artifact, directory, index)
                    paired = result['feedback']
                    feedback.extend(paired['candidates'])
                    record['paired_decision'] = result['history']
                    if result['winner']:
                        score = result['history'][0]['confirmed_improvement']
                        if state['incumbent'] is None or score > state['incumbent']['improvement']:
                            state['incumbent'] = {'proposal': selected, 'improvement': score}
                    if paired['candidates']:
                        record.update(paired['candidates'][-1])
                        state['baseline'] = paired['baseline']
                    else:
                        record['status'] = 'duplicate executable'
                    seen_elves.add(artifact.executable_sha256)
                publish_json(out / 'state.json', state)
        state['status'] = 'complete'
        publish_json(out / 'state.json', state)
    except BaseException as exc:
        state.update(status='blocked', failure=str(exc))
        publish_json(out / 'state.json', state)
        raise
    finally:
        ray.shutdown()


if __name__ == '__main__':
    main()
