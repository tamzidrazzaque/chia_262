"""Read-only, job-bound worker health; quiet UART is a warning, not a failure."""

import argparse
import json
from pathlib import Path
import shlex
import subprocess
import base64
import hashlib


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


def inspect(site, job, quiet_seconds=900):
    """Read only the UART belonging to the current job's driver."""
    p = subprocess.run(['ssh', '-i', site['ssh_key'], '-o', 'BatchMode=yes',
        '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + site['known_hosts'],
        '-o', 'ConnectTimeout=10', 'ubuntu@' + site['worker_ip'],
        'python3 -c ' + shlex.quote(WORKER_SNAPSHOT) + ' ' + shlex.quote(job)],
        capture_output=True, text=True, check=True, timeout=20)
    snapshot = json.loads(p.stdout)
    return {**snapshot, 'health': classify(snapshot, quiet_seconds)}


def stop_failed_guest(site, job, destination):
    """Archive UART before stopping only the exact admitted job's failed driver.

    Must be called by the controller for this stage, never by the status view.
    A quiet UART alone cannot authorize termination.
    """
    script = WORKER_SNAPSHOT.rsplit('print(json.dumps(', 1)[0] + r'''
import base64,hashlib,subprocess
expected=sys.argv[2]
if len(matched)!=1: raise RuntimeError('exactly one admitted driver required')
if b'Kernel panic' not in data and b'*** FAILED ***' not in data:
    raise RuntimeError('no conclusive fatal guest evidence')
pid=matched[0]
if hashlib.sha256((Path('/proc')/str(pid)/'exe').read_bytes()).hexdigest()!=expected:
    raise RuntimeError('driver identity differs')
print(json.dumps({'pid':pid,'job':job,'uart':base64.b64encode(uart.read_bytes()).decode()}),flush=True)
'''
    args = ['ssh', '-i', site['ssh_key'], '-o', 'BatchMode=yes',
        '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + site['known_hosts'],
        '-o', 'ConnectTimeout=10', 'ubuntu@' + site['worker_ip']]
    result = subprocess.run(args + ['sudo -n python3 -c ' + shlex.quote(script) + ' ' +
        shlex.quote(job) + ' ' + site['artifacts']['driver']['sha256']],
        capture_output=True, text=True, check=True, timeout=30)
    evidence = json.loads(result.stdout)
    dest = Path(destination)
    dest.mkdir(mode=0o700, parents=True, exist_ok=False)
    raw = base64.b64decode(evidence.pop('uart'), validate=True)
    (dest / 'uartlog').write_bytes(raw)
    evidence['uart_sha256'] = hashlib.sha256(raw).hexdigest()
    (dest / 'failure.json').write_text(json.dumps(evidence, indent=2) + '\n')
    # Revalidate process ownership and fatal evidence immediately before SIGTERM.
    terminate = script[:script.index('print(json.dumps(')] + r'''
if pid!=int(sys.argv[3]): raise RuntimeError('driver PID changed')
subprocess.run(['sudo','-n','kill','-TERM',str(pid)],check=True)
'''
    subprocess.run(args + ['sudo -n python3 -c ' + shlex.quote(terminate) + ' ' + shlex.quote(job) +
        ' ' + site['artifacts']['driver']['sha256'] + ' ' + str(evidence['pid'])],
        capture_output=True, text=True, check=True, timeout=30)
    return evidence


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
    quiet = {'605.mcf_s': 3600, '644.nab_s': 1800}.get(plan['identity']['benchmark'], 900)
    state['guest_health'] = inspect(site, plan['name'], quiet)
    return state


def baseline_snapshot(directory, lane):
    """Observe baseline qualification before an adaptive loop has started."""
    root, lane = Path(directory), Path(lane)
    state = json.loads((root / 'progress.json').read_text())
    role = state.get('active_role')
    dispatch = root / str(role) / 'dispatch.json'
    if role and dispatch.is_file():
        candidate = json.loads(dispatch.read_text())['candidate']
        stage = lane / 'staging' / ('auto-' + candidate.replace('.', '-'))
        if (stage / 'plan.json').is_file() and (stage / 'runworkload.started.json').is_file():
            plan = json.loads((stage / 'plan.json').read_text())
            if plan['identity']['role'] != role:
                raise ValueError('baseline guest role differs')
            site = json.loads((lane / 'platform-lock.json').read_text())
            quiet = {'605.mcf_s': 3600, '644.nab_s': 1800}.get(plan['identity']['benchmark'], 900)
            state['guest_health'] = inspect(site, plan['name'], quiet)
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--campaign', type=Path)
    mode.add_argument('--baseline', type=Path)
    parser.add_argument('--lane', type=Path)
    args = parser.parse_args()
    if args.baseline and not args.lane:
        parser.error('--baseline requires --lane')
    state = baseline_snapshot(args.baseline, args.lane) if args.baseline else campaign_snapshot(args.campaign)
    print('SATURN_STATUS:' + json.dumps(state))


if __name__ == '__main__':
    main()
