"""Manager-side receiver for one adaptive-loop candidate and fresh controls."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from examples.rocket_cost_model.saturn_bundle_artifact import SaturnBundle, unpack
from examples.rocket_cost_model.saturn_feedback_proposer import paired_feedback_state, publish_json


def failed_campaign_report(incoming: Path, request: dict, metadata: dict,
                           config: dict) -> dict:
    """Classify only failures backed by the completed manager campaign evidence.

    Unknown failures are returned as recovery-required so the controller can
    stop cleanly without pretending a candidate was measured or dispatching a
    replacement while an F2 task might still be active.
    """
    campaign_root = incoming / 'campaign'
    progress_path = campaign_root / 'progress.json'
    if not progress_path.is_file():
        raise RuntimeError('manager failed before publishing campaign progress')
    progress = json.loads(progress_path.read_text())
    failure_text = str(progress.get('failure', ''))
    campaign_log = campaign_root.parent / 'campaign.log'
    if campaign_log.is_file():
        failure_text += '\n' + campaign_log.read_text(errors='replace')
    classification = 'unclassified_manager_failure'
    evidence = {'campaign_status': progress.get('status'),
                'failure_summary': str(progress.get('failure', ''))[-1200:]}

    failed_attempts = progress.get('failed_attempts', [])
    if (progress.get('status') == 'blocked' and
            'early boot panic persisted' in failure_text and failed_attempts and
            all(x.get('role') == '2-generic-vector' and
                x.get('classification') == 'early_kernel_panic_before_guest_job'
                for x in failed_attempts)):
        classification = 'baseline_boot_retries_exhausted'
        evidence['failed_role2_attempts'] = len(failed_attempts)
    else:
        active = progress.get('active')
        artifact = (active or {}).get('artifact', {})
        if (progress.get('status') == 'blocked' and active and
                artifact.get('role') == '3-saturn-aware' and
                artifact.get('bundle_sha256') == metadata.get('manifest_sha256') and
                'guest or collection failed' in failure_text):
            lane = Path(config.get('manager_lane', incoming.parent.parent)).resolve()
            from examples.rocket_cost_model.saturn_guest_health import find_campaign_stage, inspect
            from examples.rocket_cost_model.saturn_spec.results import validate_completion
            stage = find_campaign_stage(lane, active, request)
            if stage is not None:
                plan = json.loads((stage / 'plan.json').read_text())
                image = json.loads((stage / 'image-receipt.json').read_text())
                completion = json.loads((stage / 'runworkload-completion.json').read_text())
                preflight = json.loads((stage / 'preflight.json').read_text())
                validate_completion(plan, image, completion, preflight)
                site = json.loads((lane / 'platform-lock.json').read_text())
                health = inspect(site, plan['name'])
                if health.get('matching_driver_pids'):
                    raise RuntimeError('manager failure still has a matching F2 driver')
                deploy = Path(site['chipyard_root']) / 'sims/firesim/deploy/results-workload'
                uart_hits = list(deploy.glob('*' + plan['name'] + '*/**/uartlog'))
                if len(uart_hits) == 1:
                    result = uart_hits[0].parent / 'result'
                    identity = json.loads((result / 'identity.json').read_text())
                    job_status = (result / 'job.status').read_text().strip()
                    collection_status = (result / 'collection.status').read_text().strip()
                    uart = uart_hits[0].read_bytes()
                    expected_identity = plan['identity']
                    if (identity == expected_identity and job_status.isdigit() and
                            job_status != '0' and collection_status.isdigit() and
                            collection_status != '0' and
                            b'SATURN_SPEC_JOB_EXIT=' in uart):
                        classification = 'candidate_guest_failed'
                        evidence.update(role=artifact['role'], job_status=job_status,
                            collection_status=collection_status,
                            uart_sha256=hashlib.sha256(uart).hexdigest())

    return {'campaign_status': 'failed', 'failure': {
                'classification': classification, **evidence},
            'proposal': request['proposal'], 'artifact': metadata,
            'worker_id': request['policy']['worker_id'],
            'platform_sha256': request['policy']['platform_sha256'],
            'feedback': {'baseline': {}, 'candidates': []},
            'history': [], 'winner': None}


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
    if request.get('max_guest_seconds') is not None:
        config['max_guest_seconds'] = request['max_guest_seconds']
    if request.get('manager_lane'):
        config['manager_lane'] = request['manager_lane']
    config['candidates'] = [candidate]
    publish_json(args.incoming / 'config.json', config)
    try:
        with (args.incoming / 'campaign.log').open('w') as log:
            subprocess.run([sys.executable, '-m', 'examples.rocket_cost_model.saturn_paired_run',
                '--config', str(args.incoming / 'config.json'), '--out', str(args.incoming / 'campaign')],
                check=True, stdout=log, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError:
        report = failed_campaign_report(args.incoming, request, metadata, config)
        publish_json(args.incoming / 'feedback.json', report)
        return
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
