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
        while not args.after_pilot.exists():
            if stop.wait(10):
                return
        pilot = json.loads(args.after_pilot.read_text())
        if pilot.get('status') != 'correct' or pilot.get('backend') != 'fpga':
            raise ValueError('pilot did not pass hardware correctness')
    import ray
    from ray.util.scheduling_strategies import NodeAffinitySchedulingStrategy
    from examples.rocket_cost_model.saturn_chia_tasks import measure_artifact, select_worker, await_task
    repo = Path(__file__).resolve().parents[2]
    ray.init(address=config['address'], runtime_env={'env_vars': {
        'PYTHONPATH': str(repo), 'SATURN_TASK_ROOT': config['task_root']}})
    try:
        node = select_worker(ray.nodes(), 'saturn_manager')
        options = {'scheduling_strategy': NodeAffinitySchedulingStrategy(node, soft=False)}
        policy = Policy(**config['policy'])
        artifacts = {}
        guard = threading.Lock()

        def prepare(proposal, scope, directory):
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
                'fingerprint': {'bundle_sha256': artifact.manifest_sha256,
                                'executable_sha256': artifact.executable_sha256}}

        def measure(prepared, request, directory):
            if stop.is_set():
                raise InterruptedError('campaign drain requested')
            with guard:
                artifact = artifacts[prepared['bundle_sha256']]
            # Fresh attempt namespace is independent of compiler candidate IDs.
            attempt = '3.' + str(int(request['attempt_id'][:12], 16))
            ref = measure_artifact.options(**options).chia_remote(attempt, artifact, request)
            return await_task(ref, config.get('task_alert_seconds', 28800))

        result = run(args.out, config['candidates'], policy, prepare, measure, stop)
        print(json.dumps({'status': result['status'], 'samples': len(result['samples']),
                          'winner': result['winner'] is not None}), flush=True)
    finally:
        ray.shutdown()


if __name__ == '__main__':
    main()
