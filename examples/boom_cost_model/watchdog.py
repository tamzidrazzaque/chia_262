"""Private-host health checks for an explicitly authorized continuous loop.

This is a deterministic watchdog, not a scheduled LLM/chat session. It never
retries an incomplete benchmark, signals a driver, or changes access controls.
"""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import time


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def loop_processes(root, proc_root=Path('/proc'), owned_pids=()):
    """Identify this user's exact supervisor/controller argv, not substrings."""
    supervisors, controllers = [], []
    for p in proc_root.iterdir():
        if not p.name.isdigit():
            continue
        try:
            if p.stat().st_uid != os.getuid():
                continue
            argv = (p/'cmdline').read_bytes().decode().split('\0')
            if 'examples.boom_cost_model.autopilot' in argv and '--directory' in argv:
                if Path(argv[argv.index('--directory')+1]).resolve() == root:
                    supervisors.append(int(p.name))
            modules = ('examples.boom_cost_model.focused_campaign',
                'examples.boom_cost_model.reference_check','examples.boom_cost_model.run_probes')
            if any(module in argv for module in modules):
                scoped = int(p.name) in owned_pids or any(flag in argv and
                    Path(argv[argv.index(flag)+1]).resolve().is_relative_to(root)
                    for flag in ('--run-dir','--source','--config','--probe-run-dir'))
                if scoped:
                    controllers.append(int(p.name))
        except (OSError, UnicodeError, ValueError, IndexError):
            continue
    return supervisors, controllers


def driver_states(config):
    """Treat SSH errors as unknown; never confuse them with an idle FPGA."""
    states = {}
    for worker in config['fpga_workers']:
        alias = worker['ssh_alias']
        if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', alias):
            raise ValueError('invalid SSH alias')
        try:
            p = subprocess.run(['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',
                '-o','ConnectTimeout=15',alias,'pgrep -x FireSim-f2'],
                capture_output=True,text=True,timeout=30)
            states[alias] = 'active' if p.returncode == 0 else 'idle' if p.returncode == 1 else 'unknown'
        except subprocess.TimeoutExpired:
            states[alias] = 'unknown'
    return states


def authentication(config):
    """Ask the AWS CLI for identity without reading or persisting credentials."""
    try:
        p = subprocess.run(['aws','--profile',config['aws_profile'],'--region',config['region'],
            'sts','get-caller-identity','--output','json','--no-cli-pager',
            '--cli-connect-timeout','5','--cli-read-timeout','10'],
            capture_output=True,text=True,timeout=60)
    except subprocess.TimeoutExpired:
        return 'unknown'
    if p.returncode:
        return 'expired' if 'expired' in p.stderr.lower() else 'unknown'
    try:
        identity = json.loads(p.stdout)
    except ValueError:
        return 'unknown'
    expected = 'arn:aws:iam::'+config['aws_account']+':user/'+config['iam_user']
    return 'verified' if identity.get('Arn') == expected else 'wrong-identity'


def recovery_action(state, complete, supervisors, controllers, drivers, stopped):
    """Only a completed, fully idle loop can qualify for supervisor recovery."""
    if stopped or state.get('stop_requested') or state.get('phase') == 'stopped':
        return 'stopped'
    if supervisors:
        return 'supervised-preflight-blocked' if state.get('phase') in ('blocked','waiting-for-preflight') else 'supervised'
    if controllers or 'active' in drivers.values():
        return 'preserve-active-work'
    if not complete:
        return 'investigate-incomplete-run'
    if not drivers or any(v != 'idle' for v in drivers.values()):
        return 'connectivity-unknown'
    return 'verify-before-restart'


def start_supervisor(config, directory):
    """Start in the owner's tmux, preserving its existing windows and panes."""
    session = config.get('tmux_session','chia')
    if not re.fullmatch(r'[A-Za-z0-9_-]+', session):
        raise ValueError('invalid tmux session')
    if subprocess.run(['tmux','has-session','-t',session],capture_output=True).returncode:
        subprocess.run(['tmux','new-session','-d','-s',session],check=True)
    argv = [config['python'],'-u','-m','examples.boom_cost_model.autopilot',
        '--initial-run',config['initial_run'],'--directory',config['root'],
        '--settings',str(Path(config['root'])/'settings.json')]
    command = 'source '+shlex.quote(config['environment'])+'\nexec '+shlex.join(argv)
    command += ' >> '+shlex.quote(str(directory/'recovered-supervisor.log'))+' 2>&1'
    subprocess.run(['tmux','new-window','-d','-t',session,'-n','autopilot-recovery',
        shlex.join(['bash','-lc',command])],check=True)


def check(config, force_audit=False):
    """Audit periodically, and recover a completed orphaned loop at most once."""
    root = Path(config['root']).resolve()
    directory = root/'monitor'
    directory.mkdir(exist_ok=True)
    lock = (directory/'watchdog.lock').open('w')
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        return {'action':'previous-check-active'}
    now = time.time()
    previous = read(directory/'status.json') if (directory/'status.json').exists() else {}
    state = read(root/'state.json')
    settings = read(root/'settings.json')
    stopped = bool(state.get('stop_requested') or state.get('phase') == 'stopped') or any(
        p.exists() for p in [directory/'STOP',root/'STOP',
            *[Path(v) for v in settings.get('external_stop_controls',[])]])
    current = Path(state['current']).resolve()
    if not current.is_relative_to(root):
        raise ValueError('current run is outside the watched root')
    campaign = read(current.parent/'config.json')
    supervisors, controllers = loop_processes(root,Path('/proc'),state.get('owned_pids',()))
    audit = force_audit or now-previous.get('last_audit',0) >= config.get('audit_seconds',1800)
    remote = not stopped and (audit or not supervisors or state.get('phase') in ('blocked','waiting-for-preflight'))
    drivers = driver_states(campaign) if remote else previous.get('drivers',{})
    complete = (current/'result.json').exists() and read(current/'result.json').get('complete',False)
    action = recovery_action(state,complete,supervisors,controllers,drivers,stopped)
    status = {'checked_at':now,'last_audit':now if audit else previous.get('last_audit',0),
        'round':state.get('round'),'phase':state.get('phase'),'supervisor_pids':supervisors,
        'controller_pids':controllers,'drivers':drivers,'action':action,
        'drivers_checked_at':now if remote else previous.get('drivers_checked_at'),
        'authentication':authentication(campaign) if remote
            else previous.get('authentication','not-checked')}
    progress_path = current/'progress.json'
    if progress_path.exists():
        progress = read(progress_path)
        status['worker_stages'] = progress.get('active')
        status['completed_trials'] = [{k:h[k] for k in ('index','success','train_times') if k in h}
            for h in progress.get('history',[])]
    if action == 'verify-before-restart':
        from examples.boom_cost_model import autopilot
        ledger_path = directory/'recoveries.json'
        ledger = read(ledger_path) if ledger_path.exists() else {}
        fingerprint = hashlib.sha256(json.dumps({'current':str(current),
            'completed_result':autopilot.digest(current/'result.json'),
            'source':autopilot.digest(Path(autopilot.__file__))},sort_keys=True).encode()).hexdigest()
        if fingerprint in ledger:
            status['action'] = 'repeated-failure-needs-investigation'
        elif status['authentication'] != 'verified':
            status['action'] = 'authentication-required'
        else:
            try:
                # Existing review validates finality, immutable artifacts and later
                # failure/stop records. Full normal preflight still runs at launch.
                autopilot.review(current)
                autopilot.dispatch_ready(campaign)
                if loop_processes(root,Path('/proc'),state.get('owned_pids',())) != ([],[]):
                    status['action'] = 'process-started-during-check'
                elif stopped or any(p.exists() for p in [directory/'STOP',root/'STOP',
                        *[Path(v) for v in settings.get('external_stop_controls',[])]]):
                    status['action'] = 'stopped'
                else:
                    ledger[fingerprint] = now
                    write(ledger_path,ledger)
                    write(directory/('state-before-recovery-'+str(time.time_ns())+'.json'),state)
                    for field in ('failure','blocker','child_pid','owned_pids','active','completed_profiles'):
                        state.pop(field,None)
                    state['phase'] = 'watchdog-recovery-ready'
                    autopilot.write(root/'state.json',state)
                    start_supervisor(config,directory)
                    status['action'] = 'supervisor-restarted'
            except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as exc:
                status.update(action='preflight-or-finality-check-failed',error_type=type(exc).__name__)
    reason = None if stopped else ('authentication-'+status['authentication'] if status['authentication'] in ('expired','wrong-identity')
        else 'driver-connectivity-unknown' if 'unknown' in drivers.values() and not stopped
        else status['action'] if status['action'] not in (
            'supervised','preserve-active-work','stopped','supervisor-restarted') else None)
    if reason:
        status['attention_reason'] = reason
        write(directory/'attention.json',status)
        if reason != previous.get('attention_reason') or audit:
            subprocess.run(['tmux','display-message','-t',config.get('tmux_session','chia'),
                'Chia needs attention: '+reason+'; see '+str(directory/'attention.json')],capture_output=True)
    else:
        (directory/'attention.json').unlink(missing_ok=True)
    write(directory/'status.json',status)
    if audit or status['action'] != previous.get('action'):
        with (directory/'audits.jsonl').open('a') as stream:
            stream.write(json.dumps(status)+'\n')
        print(json.dumps(status),flush=True)
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--audit',action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    check(read(args.config),args.audit)


if __name__ == '__main__':
    main()
