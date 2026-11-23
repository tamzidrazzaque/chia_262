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


def campaign_status(config, remote_run):
    """Read only the campaign dispatched by this candidate, with bounded SSH."""
    progress = str(Path(remote_run) / 'campaign/progress.json')
    script = ('import json; from pathlib import Path; p=Path(' + repr(progress) + '); '
              'print("SATURN_STATUS:"+json.dumps(json.loads(p.read_text()) '
              'if p.is_file() else {"status":"starting"}))')
    command = 'python3 -c ' + shlex.quote(script)
    output = subprocess.run(['ssh', '-T', '-i', config['manager_key'],
        '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
        '-o', 'ConnectTimeout=10', config['manager_host'], command],
        capture_output=True, text=True, check=True, timeout=20).stdout
    records = [line.removeprefix('SATURN_STATUS:') for line in output.splitlines()
               if line.startswith('SATURN_STATUS:')]
    if len(records) != 1:
        raise ValueError('invalid status response')
    return json.loads(records[0])


def summary(name, entry, local_only=False):
    """Return a snapshot without writing files, acquiring leases or dispatching work."""
    root = Path(entry['run'])
    path = root / 'state.json'
    state = read(path)
    records = state.get('candidates', [])
    current = records[-1] if records else {}
    lines = [f"{name}: {state['status']} | candidate {current.get('candidate_id', '-')} "
             f"{current.get('status', '-')}",
             f"  Measured: {state.get('measured_candidates', 0)} | "
             f"duplicates skipped: {sum(r.get('status') == 'duplicate executable' for r in records)} | "
             f"queued: {state.get('pending_proposals', 0)} | "
             f"state updated {max(0, int(time.time() - path.stat().st_mtime))}s ago"]
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
