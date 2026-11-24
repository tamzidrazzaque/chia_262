"""Read-only terminal status for existing continuous Saturn loops (no Ray needed)."""

import argparse
from datetime import datetime
import json
from pathlib import Path
import shlex
import subprocess
import time
from zoneinfo import ZoneInfo


def read(path):
    """Read an atomically published JSON record."""
    return json.loads(Path(path).read_text())


def campaign_status(config, remote_run, baseline=False):
    """Read only the campaign dispatched by this candidate, with bounded SSH."""
    command = ('cd ' + shlex.quote(config['manager_repo']) + ' && ' +
               shlex.quote(config['manager_python']) +
               ' -m examples.rocket_cost_model.saturn_guest_health ' +
               ('--baseline ' if baseline else '--campaign ') + shlex.quote(remote_run))
    if baseline:
        command += ' --lane ' + shlex.quote(config['manager_lane'])
        if config.get('diagnosis_progress'):
            command += ' --diagnosis-progress ' + shlex.quote(config['diagnosis_progress'])
    output = subprocess.run(['ssh', '-T', '-i', config['manager_key'],
        '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
        '-o', 'ConnectTimeout=10', config['manager_host'], command],
        capture_output=True, text=True, check=True, timeout=55).stdout
    records = [line.removeprefix('SATURN_STATUS:') for line in output.splitlines()
               if line.startswith('SATURN_STATUS:')]
    if len(records) != 1:
        raise ValueError('invalid status response')
    return json.loads(records[0])


def summary(name, entry, local_only=False):
    """Return a snapshot without writing files, acquiring leases or dispatching work."""
    root = Path(entry['run'])
    path = root / 'state.json'
    if not path.is_file() and entry.get('activation'):
        activation = read(Path(entry['activation']) / 'activation.json')
        text = (f"{name}: {'diagnosis_hold' if entry.get('hold_reason') else activation['status']} | baseline role: "
                f"{activation.get('active_baseline_role', '-')}\n"
                '  Candidate loop waits for both hardware baselines to pass.')
        if entry.get('hold_reason'):
            text += '\n  ' + entry['hold_reason']
        if not local_only and entry.get('manager_config'):
            try:
                config = read(entry['manager_config'])
                remote = campaign_status(config, str(Path(config['activation_gate']['progress']).parent), baseline=True)
                text += (f"\n  Baseline gate: {remote.get('status', '-')} | "
                         f"active role: {remote.get('active_role', '-')} | passed roles: {len(remote.get('roles', []))}")
                text += '\n  Guest: ' + remote.get('guest_health', {}).get('health', 'preparing hardware task')
                if remote.get('diagnosis'):
                    diagnosis = remote['diagnosis']
                    text += (f"\n  Boot comparison: {diagnosis.get('status')} | "
                             f"attempt: {diagnosis.get('active_attempt') or '-'} | completed: {len(diagnosis.get('attempts', []))}")
                    if diagnosis.get('guest_health'):
                        text += '\n  Diagnostic guest: ' + diagnosis['guest_health']['health']
                if remote.get('guest_health', {}).get('health', '').startswith('FAILED:'):
                    text = text.replace(f'{name}: ', f'{name}: GUEST FAILED | ', 1)
            except (OSError, ValueError, KeyError, subprocess.SubprocessError):
                text += '\n  Baseline manager status unavailable.'
        return text
    state = read(path)
    records = state.get('candidates', [])
    current = records[-1] if records else {}
    lines = [f"{name}: {state['status']} | candidate {current.get('candidate_id', '-')} "
             f"{current.get('status', '-')}",
             f"  Measured: {state.get('measured_candidates', 0)} | "
             f"duplicates skipped: {sum(r.get('status') == 'duplicate executable' for r in records)} | "
             f"queued: {state.get('pending_proposals', 0)} | "
             f"state updated {max(0, int(time.time() - path.stat().st_mtime))}s ago"]
    if entry.get('service'):
        try:
            result = subprocess.run(['systemctl', '--user', 'show', '--property=ActiveState,SubState,MainPID',
                '--', entry['service']], capture_output=True, text=True, check=True, timeout=5)
            service = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
            lines.append(f"  Controller service: {service.get('ActiveState', 'unknown')}/{service.get('SubState', '-')} "
                         f"| PID: {service.get('MainPID', '-')}")
            if service.get('ActiveState') != 'active':
                lines[0] = lines[0].replace(f'{name}: ', f'{name}: CONTROLLER STOPPED | recorded ', 1)
        except (OSError, ValueError, subprocess.SubprocessError):
            lines.append('  Controller service observation unavailable.')
    if current.get('proposal', {}).get('changes'):
        lines.append('  Costs: ' + json.dumps(current['proposal']['changes'], sort_keys=True))
    measured = [r for r in records if r.get('cycles') and r.get('baseline_cycles')]
    if measured:
        latest = measured[-1]
        gain = 100 * (1 - latest['cycles'] / latest['baseline_cycles'])
        lines.append(f"  Latest pair {latest['candidate_id']}: {latest['cycles']:,} candidate / "
                     f"{latest['baseline_cycles']:,} baseline cycles ({gain:+.3f}% reduction)")
    incumbent = state.get('incumbent')
    lines.append('  Confirmed winner: ' + (
        f"{incumbent['proposal']['candidate_id']} ({incumbent['improvement']:+.2%})"
        if incumbent else 'none'))
    if state.get('provider_error_type'):
        lines.append('  Model access: ' + state['provider_error_type'])
    if state.get('failure'):
        lines.append('  Failure recorded; inspect the private loop state/log.')
    dispatch = root / str(current.get('candidate_id', '')) / 'dispatch.json'
    if not local_only and current.get('status') == 'measuring' and dispatch.is_file():
        try:
            config = read(entry['manager_config'])
            remote = campaign_status(config, read(dispatch)['remote_run'])
            active = remote.get('active') or {}
            lines.append(f"  Manager: {remote.get('status', 'unknown')} | "
                         f"active role: {active.get('artifact', {}).get('role', '-')} | "
                         f"completed samples: {len(remote.get('samples', []))}")
            retries = remote.get('failed_attempts', [])
            if retries:
                lines.append(f"  Verified early-boot retries: {len(retries)}")
            health = remote.get('guest_health', {})
            if health.get('health', '').startswith('FAILED:'):
                lines[0] = lines[0].replace(f'{name}: ', f'{name}: GUEST FAILED | recorded loop ', 1)
            lines.append('  Guest: ' + health.get('health', 'not observed'))
            if health.get('uart_age_seconds') is not None:
                lines.append(f"  UART last changed {int(health['uart_age_seconds'])}s ago")
            if remote.get('samples'):
                sample = remote['samples'][-1]
                lines.append(f"  Last collected: {sample['role']} | {sample['cycles']:,} cycles (pair may be incomplete)")
        except (OSError, ValueError, KeyError, subprocess.SubprocessError):
            lines.append('  Manager status unavailable (read-only check failed).')
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True,
                        help='private JSON mapping labels to run and manager_config paths')
    parser.add_argument('--local', action='store_true', help='skip read-only manager SSH')
    args = parser.parse_args()
    print(datetime.now(ZoneInfo('America/Los_Angeles')).strftime('%Y-%m-%d %H:%M:%S %Z'))
    print('Recorded loop state; this command does not control the runners.\n')
    for name, entry in read(args.config).items():
        try:
            print(summary(name, entry, args.local))
        except (OSError, ValueError, KeyError):
            print(f'{name}: state unavailable')
        print()


if __name__ == '__main__':
    main()
