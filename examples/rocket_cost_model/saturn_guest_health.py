"""Read-only, job-bound worker health; quiet UART is a warning, not a failure."""

import argparse
import json
from pathlib import Path
import shlex
import subprocess


WORKER_SNAPSHOT = r'''
import json,os,time
from pathlib import Path
import sys
job=sys.argv[1]
slot=Path('/home/ubuntu/sim_slot_0')
matched=[]
for p in Path('/proc').iterdir():
    if not p.name.isdigit(): continue
    try:
        if (p/'comm').read_text().strip() != 'FireSim-f2': continue
        args=(p/'cmdline').read_bytes().decode().split('\0')
        if any(a.startswith('+prog0='+job+'0-') for a in args): matched.append(int(p.name))
    except (OSError,UnicodeError): pass
uart=slot/'uartlog'
data=b''
age=None
if uart.is_file():
    age=max(0,time.time()-uart.stat().st_mtime)
    with uart.open('rb') as f:
        f.seek(max(0,uart.stat().st_size-131072)); data=f.read()
print(json.dumps({'matching_driver_pids':matched,'uart_age_seconds':age,
 'kernel_panic':b'Kernel panic' in data,
 'kernel_oops':b'Unable to handle kernel' in data or b'Internal error:' in data,
 'simulation_failed':b'*** FAILED ***' in data,
 'simulation_passed':b'*** PASSED ***' in data,
 'workload_launched':b'launching firemarshal workload' in data,
 'job_exit_seen':b'SATURN_SPEC_JOB_EXIT=' in data}))
'''


def classify(snapshot, quiet_seconds=900):
    """Distinguish fatal UART evidence from an inconclusive quiet driver."""
    if not snapshot.get('matching_driver_pids'):
        return 'no matching driver (starting, finished, or unavailable)'
    if snapshot.get('kernel_panic'):
        return 'FAILED: guest kernel panic'
    if snapshot.get('kernel_oops') or snapshot.get('simulation_failed'):
        return 'FAILED: guest/kernel simulation error'
    age = snapshot.get('uart_age_seconds')
    if age is not None and age >= quiet_seconds:
        return 'WARNING: quiet guest; forward progress unconfirmed'
    return 'driver active; no fatal UART evidence'


def inspect(site, job):
    """Read only the UART belonging to the current job's driver."""
    p = subprocess.run(['ssh', '-i', site['ssh_key'], '-o', 'BatchMode=yes',
        '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + site['known_hosts'],
        '-o', 'ConnectTimeout=10', 'ubuntu@' + site['worker_ip'],
        'python3 -c ' + shlex.quote(WORKER_SNAPSHOT) + ' ' + shlex.quote(job)],
        capture_output=True, text=True, check=True, timeout=20)
    snapshot = json.loads(p.stdout)
    return {**snapshot, 'health': classify(snapshot)}


def campaign_snapshot(remote_run):
    """Resolve the campaign's exact attempt to its admitted worker and job."""
    root = Path(remote_run)
    p = root / 'campaign/progress.json'
    if not p.is_file():
        return {'status': 'starting'}
    state = json.loads(p.read_text())
    active = state.get('active')
    if not active:
        return state
    request = json.loads((root / 'request.json').read_text())
    lane = Path(request.get('manager_lane', root.parent.parent))
    attempt = str(int(active['request']['attempt_id'][:12], 16))
    stage = lane / 'staging' / ('auto-3-' + attempt)
    if not (stage / 'plan.json').is_file() or not (stage / 'runworkload.started.json').is_file():
        state['guest_health'] = {'health': 'preparing hardware task'}
        return state
    plan = json.loads((stage / 'plan.json').read_text())
    site = json.loads((lane / 'platform-lock.json').read_text())
    if plan['identity']['bundle_sha256'] != active['artifact']['bundle_sha256']:
        raise ValueError('active guest belongs to another bundle')
    state['guest_health'] = inspect(site, plan['name'])
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', type=Path, required=True)
    args = parser.parse_args()
    print('SATURN_STATUS:' + json.dumps(campaign_snapshot(args.campaign)))


if __name__ == '__main__':
    main()
