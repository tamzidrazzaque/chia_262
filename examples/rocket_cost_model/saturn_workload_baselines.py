"""Run scalar then stock-vector correctness pilots on an admitted second lane."""

import argparse
import json
from pathlib import Path
import subprocess
import sys

from examples.rocket_cost_model.saturn_feedback_proposer import publish_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundles', type=Path, required=True)
    parser.add_argument('--lane', type=Path, required=True)
    parser.add_argument('--address', required=True)
    parser.add_argument('--task-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--first-attempt', type=int, required=True)
    args = parser.parse_args()
    args.out.mkdir(mode=0o700, parents=True, exist_ok=False)
    state = {'status': 'running', 'roles': []}
    publish_json(args.out / 'progress.json', state)
    try:
        for offset, role in enumerate(('1-scalar', '2-generic-vector')):
            state['active_role'] = role
            publish_json(args.out / 'progress.json', state)
            destination = args.out / role
            with (args.out / (role + '.log')).open('w') as log:
                subprocess.run([sys.executable, '-m', 'examples.rocket_cost_model.saturn_artifact_pilot',
                    '--bundle', str(args.bundles / role), '--candidate', '3.' + str(args.first_attempt + offset),
                    '--lane', str(args.lane), '--address', args.address,
                    '--phase', 'baseline', '--sample', str(offset),
                    '--task-root', str(args.task_root), '--out', str(destination), '--execute'],
                    check=True, stdout=log, stderr=subprocess.STDOUT)
            receipt = json.loads((destination / 'receipt.json').read_text())
            if receipt.get('status') != 'correct' or receipt['identity']['role'] != role:
                raise ValueError('baseline pilot correctness/role mismatch')
            state['roles'].append({'role': role, 'cycles': receipt['whole_boot_simulation_cycles'],
                                   'identity': receipt['identity']})
            publish_json(args.out / 'progress.json', state)
        a, b = (item['identity'] for item in state['roles'])
        for key in ('worker_id', 'platform_sha256', 'input_id', 'benchmark'):
            if a[key] != b[key]:
                raise ValueError('scalar/vector pilot identities differ')
        state.update(status='complete', active_role=None)
        publish_json(args.out / 'progress.json', state)
    except BaseException as exc:
        state.update(status='blocked', failure=str(exc))
        publish_json(args.out / 'progress.json', state)
        raise


if __name__ == '__main__':
    main()
