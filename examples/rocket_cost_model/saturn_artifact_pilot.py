"""Run one admitted Saturn bundle through CHIA transfer validation or F2."""

import argparse
import json
from pathlib import Path

from examples.rocket_cost_model.saturn_feedback_proposer import publish_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--address', required=True)
    parser.add_argument('--task-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    # Exclusive run directory is an attempt guard, including driver crashes.
    args.out.mkdir(mode=0o700, parents=True, exist_ok=False)
    try:
        execute(args)
    except BaseException as exc:
        publish_json(args.out / 'failed.json', {
            'status': 'failed', 'exception_type': type(exc).__name__,
            'message': str(exc), 'candidate': args.candidate})
        raise


def execute(args):
    from examples.rocket_cost_model.saturn_bundle_artifact import pack
    from examples.rocket_cost_model.saturn_chia_tasks import (
        validate_artifact, measure_artifact, select_worker, await_task)
    import ray
    from ray.util.scheduling_strategies import NodeAffinitySchedulingStrategy
    repo = Path(__file__).resolve().parents[2]
    ray.init(address=args.address, runtime_env={'env_vars': {
        'PYTHONPATH': str(repo), 'SATURN_TASK_ROOT': str(args.task_root.resolve())}})
    try:
        node = select_worker(ray.nodes(), 'saturn_manager')
        options = {'scheduling_strategy': NodeAffinitySchedulingStrategy(node, soft=False)}
        artifact = pack(args.bundle)
        admission = await_task(validate_artifact.options(**options).chia_remote(artifact), 60)
        publish_json(args.out / 'artifact-admission.json', admission)
        if args.execute:
            publish_json(args.out / 'dispatch.json', {
                'candidate': args.candidate, 'bundle_sha256': artifact.manifest_sha256,
                'executable_sha256': artifact.executable_sha256, 'node_id': node})
            receipt = await_task(measure_artifact.options(**options).chia_remote(
                args.candidate, artifact), 28800)
            publish_json(args.out / 'receipt.json', receipt)
        print('CHIA artifact admission passed' + ('; F2 receipt collected' if args.execute else ''))
    finally:
        ray.shutdown()


if __name__ == '__main__':
    main()
