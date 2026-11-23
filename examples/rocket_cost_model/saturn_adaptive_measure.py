"""Manager-side receiver for one adaptive-loop candidate and fresh controls."""

import argparse
import json
from pathlib import Path
import subprocess
import sys

from examples.rocket_cost_model.saturn_bundle_artifact import SaturnBundle, unpack
from examples.rocket_cost_model.saturn_feedback_proposer import paired_feedback_state, publish_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--incoming', type=Path, required=True)
    args = parser.parse_args()
    request = json.loads((args.incoming / 'request.json').read_text())
    metadata = request['artifact']
    artifact = SaturnBundle((args.incoming / 'artifact.tar').read_bytes(), **metadata)
    unpack(artifact, args.incoming / 'bundle')
    candidate = {**request['proposal'], 'bundles': {request['policy']['scope']: str(args.incoming / 'bundle')}}
    config = {key: request[key] for key in ('address', 'task_root', 'policy', 'baseline')}
    if request.get('manager_lane'):
        config['manager_lane'] = request['manager_lane']
    config['candidates'] = [candidate]
    publish_json(args.incoming / 'config.json', config)
    with (args.incoming / 'campaign.log').open('w') as log:
        subprocess.run([sys.executable, '-m', 'examples.rocket_cost_model.saturn_paired_run',
            '--config', str(args.incoming / 'config.json'), '--out', str(args.incoming / 'campaign')],
            check=True, stdout=log, stderr=subprocess.STDOUT)
    state = paired_feedback_state(args.incoming / 'campaign', args.incoming)
    campaign = json.loads((args.incoming / 'campaign/progress.json').read_text())
    publish_json(args.incoming / 'feedback.json', {
        'feedback': state, 'proposal': request['proposal'], 'artifact': metadata,
        'worker_id': request['policy']['worker_id'],
        'platform_sha256': request['policy']['platform_sha256'],
        'campaign_status': campaign['status'], 'history': campaign['history'],
        'winner': campaign['winner']})


if __name__ == '__main__':
    main()
