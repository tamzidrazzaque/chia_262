"""Connect the paired campaign policy to admitted CHIA bundle tasks."""

import argparse
import hashlib
import json
from pathlib import Path
import signal
import threading
import time

from examples.rocket_cost_model.saturn_bundle_artifact import pack, artifact_role
from examples.rocket_cost_model.saturn_paired_campaign import Policy, run


def validate_pilot(pilot, config):
    """Bind the launch gate to this campaign's physical worker and candidates."""
    identity = pilot.get('identity', {})
    policy = config['policy']
    if pilot.get('status') != 'correct' or pilot.get('backend') != 'fpga':
        raise ValueError('pilot did not pass hardware correctness')
    for key in ('platform_sha256', 'worker_id'):
        if identity.get(key) != policy[key]:
            raise ValueError('pilot belongs to a different platform or physical worker')
    if identity.get('role') != '3-saturn-aware':
        raise ValueError('role-3 pilot required')
    candidates = {}
    for candidate in config['candidates']:
        source = Path(candidate['bundles'][policy.get('scope', 'train')])
        data = (source / 'manifest.json').read_bytes()
        manifest = json.loads(data)
        candidates[hashlib.sha256(data).hexdigest()] = manifest
    manifest = candidates.get(identity.get('bundle_sha256'))
    if manifest is None or identity.get('input_id') != manifest.get('input_id'):
        raise ValueError('pilot bundle is not one of the configured candidate inputs')
    if pilot.get('executable_sha256') != manifest['files_sha256'][manifest['executable']]:
        raise ValueError('pilot executable differs from configured candidate')
    if type(pilot.get('whole_boot_simulation_cycles')) is not int or pilot['whole_boot_simulation_cycles'] <= 0:
        raise ValueError('pilot lacks a positive cycle count')


def workload_identity(manifest):
    """Compare actual input/reference bytes and invocation across paired roles."""
    value = {key: manifest[key] for key in ('size', 'input_id', 'argv', 'stdin', 'stdout', 'stderr')}
    for key in ('inputs', 'expected_outputs'):
        value[key] = {name: manifest['files_sha256'][path] for name, path in manifest[key].items()}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def wait_for_pilot(path, config, stop, interval=10, timeout=28800):
    """Wait for an atomic success receipt, propagate failure, and bound the wait."""
    deadline = time.monotonic() + timeout
    while not stop.is_set():
        failure = path.parent / 'failed.json'
        if failure.exists():
            raise RuntimeError('pilot failed; inspect its private failed.json before retrying')
        if path.exists():
            try:
                pilot = json.loads(path.read_text())
            except json.JSONDecodeError:
                pass  # tolerate a receipt from the older non-atomic publisher
            else:
                validate_pilot(pilot, config)
                return True
        if time.monotonic() >= deadline:
            raise TimeoutError('pilot did not publish a receipt before the gate deadline')
        stop.wait(interval)
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--after-pilot', type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    if args.after_pilot:
        print('Waiting for the pilot receipt before campaign dispatch', flush=True)
        if not wait_for_pilot(args.after_pilot, config, stop):
            return
    import ray
    from ray.util.scheduling_strategies import NodeAffinitySchedulingStrategy
    from examples.rocket_cost_model.saturn_chia_tasks import measure_artifact, select_worker, await_task
    repo = Path(__file__).resolve().parents[2]
    environment = {'PYTHONPATH': str(repo), 'SATURN_TASK_ROOT': config['task_root']}
    if config.get('manager_lane'):
        environment['SATURN_MANAGER_LANE'] = config['manager_lane']
    ray.init(address=config['address'], runtime_env={'env_vars': environment})
    try:
        node = select_worker(ray.nodes(), 'saturn_manager')
        options = {'scheduling_strategy': NodeAffinitySchedulingStrategy(node, soft=False)}
        policy = Policy(**config['policy'])
        artifacts = {}
        guard = threading.Lock()

        def prepare(proposal, scope, directory):
            # This CLI currently packages existing validated bundles. The core
            # campaign also permits a compiler/SPEC producer callback.
            selected = config['baseline'] if proposal is None else proposal
            source = Path(selected['bundles'][scope])
            artifact = pack(source)
            manifest = json.loads((source / 'manifest.json').read_text())
            if manifest['size'] != scope:
                raise ValueError('bundle input size differs from requested scope')
            with guard:
                artifacts[artifact.manifest_sha256] = artifact
            return {'role': artifact_role(artifact), 'scope': scope,
                'input_id': manifest['input_id'], 'bundle_sha256': artifact.manifest_sha256,
                'executable_sha256': artifact.executable_sha256,
                'workload_sha256': workload_identity(manifest),
                'fingerprint': {'bundle_sha256': artifact.manifest_sha256,
                                'executable_sha256': artifact.executable_sha256}}

        def measure(prepared, request, directory):
            if stop.is_set():
                raise InterruptedError('campaign drain requested')
            with guard:
                artifact = artifacts[prepared['bundle_sha256']]
            # Fresh attempt namespace is independent of compiler candidate IDs.
            attempt = '3.' + str(int(request['attempt_id'][:12], 16))
            task_request = dict(request)
            if config.get('max_guest_seconds') is not None:
                limit = config['max_guest_seconds']
                if type(limit) is not int or not 60 <= limit <= 3600:
                    raise ValueError('max_guest_seconds must be an integer from 60 through 3600')
                task_request['max_guest_seconds'] = limit
            ref = measure_artifact.options(**options).chia_remote(attempt, artifact, task_request)
            return await_task(ref, config.get('task_alert_seconds', 28800))

        result = run(args.out, config['candidates'], policy, prepare, measure, stop)
        print(json.dumps({'status': result['status'], 'samples': len(result['samples']),
                          'winner': result['winner'] is not None}), flush=True)
    finally:
        ray.shutdown()


if __name__ == '__main__':
    main()
