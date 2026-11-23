"""Start the existing continuous runner after a workload's baseline gate passes."""

import argparse
import fcntl
import json
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import threading
import uuid
import time

from examples.rocket_cost_model.saturn_adaptive_loop import ssh
from examples.rocket_cost_model.saturn_feedback_proposer import publish_json


def validate_gate(status, config):
    """Require the exact workload, baseline bundles, platform and worker."""
    if status.get('status') != 'complete':
        raise ValueError('baseline gate is not complete')
    roles = {entry['role']: entry for entry in status['roles']}
    if len(status['roles']) != 2 or set(roles) != {'1-scalar', '2-generic-vector'}:
        raise ValueError('both baseline roles must pass')
    gate = config['activation_gate']
    for role, entry in roles.items():
        identity = entry['identity']
        if identity.get('role') != role:
            raise ValueError('baseline receipt role mismatch')
        for key in ('worker_id', 'platform_sha256'):
            if identity.get(key) != config['policy'][key]:
                raise ValueError('baseline physical worker/platform mismatch')
        if identity.get('benchmark') != config['benchmark'] or identity.get('phase') != 'baseline':
            raise ValueError('baseline workload/phase mismatch')
        if identity.get('bundle_sha256') != gate['expected_bundles'][role]:
            raise ValueError('baseline bundle differs from admitted payload')
        if type(entry.get('cycles')) is not int or entry['cycles'] <= 0:
            raise ValueError('baseline lacks positive target cycles')
    if roles['1-scalar']['identity']['input_id'] != roles['2-generic-vector']['identity']['input_id']:
        raise ValueError('baseline input identities differ')
    return roles['2-generic-vector']['cycles']


def fetch_status(config):
    marker = 'SATURN_BASELINE_' + uuid.uuid4().hex
    path = shlex.quote(config['activation_gate']['progress'])
    command = 'echo ' + shlex.quote(marker) + '; if test -f ' + path + \
        '; then cat ' + path + "; else printf '%s' '{\"status\":\"not_started\"}'; fi"
    output = ssh(config, command, capture_output=True, text=True).stdout
    if output.count(marker + '\n') != 1:
        raise ValueError('invalid baseline status transfer')
    return json.loads(output.split(marker + '\n', 1)[1])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--poll-seconds', type=float, default=30)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    args.out.mkdir(mode=0o700, parents=True, exist_ok=True)
    child = [None]
    stop = threading.Event()
    def drain(*_):
        stop.set()
        if child[0] is not None and child[0].poll() is None:
            child[0].send_signal(signal.SIGTERM)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, drain)
    with (args.out / 'activation.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = {'status': 'waiting_for_baselines', 'benchmark': config['benchmark']}
        deadline = time.monotonic() + config.get('activation_timeout_seconds', 86400)
        try:
            while not stop.is_set():
                if time.monotonic() >= deadline:
                    raise TimeoutError('workload baseline gate did not complete before its deadline')
                status = fetch_status(config)
                if stop.is_set():
                    break
                if status.get('status') in ('blocked', 'failed'):
                    raise RuntimeError('baseline gate failed; inspect private baseline evidence')
                if status.get('status') == 'complete':
                    cycles = validate_gate(status, config)
                    config['initial_feedback'] = {'baseline': {'cycles': cycles}, 'candidates': []}
                    state.update(status='launching_adaptive_loop', baseline_cycles=cycles)
                    publish_json(args.out / 'activation.json', state)
                    runtime_config = args.out / 'admitted-config.json'
                    publish_json(runtime_config, config)
                    if stop.is_set():
                        break
                    child[0] = subprocess.Popen([sys.executable, '-m',
                        'examples.rocket_cost_model.saturn_adaptive_loop',
                        '--config', str(runtime_config), '--out', str(args.out / 'loop')])
                    if stop.is_set() and child[0].poll() is None:
                        child[0].send_signal(signal.SIGTERM)
                    rc = child[0].wait()
                    if rc and not stop.is_set():
                        raise RuntimeError('adaptive child stopped; inspect its recorded state')
                    state['status'] = 'drained' if stop.is_set() else 'complete'
                    publish_json(args.out / 'activation.json', state)
                    return
                state.update(active_baseline_role=status.get('active_role'))
                publish_json(args.out / 'activation.json', state)
                stop.wait(args.poll_seconds)
            state['status'] = 'drained'
            publish_json(args.out / 'activation.json', state)
        except BaseException as exc:
            state.update(status='blocked', failure=str(exc))
            publish_json(args.out / 'activation.json', state)
            raise


if __name__ == '__main__':
    main()
