"""Bound a native task and stop a conclusively failed, hash-bound guest driver."""

import argparse
import json
from pathlib import Path
import subprocess
import time

from examples.rocket_cost_model.saturn_guest_health import inspect, stop_failed_guest, stop_diagnostic_guest


class GuestFailure(RuntimeError):
    """A matching driver produced conclusive fatal guest evidence."""


class DiagnosticEnd(RuntimeError):
    """An explicitly diagnostic run reached its host time budget."""


def run(stage, command, interval=30, evidence_directory=None, process_kwargs=None, diagnostic_seconds=None):
    """Run one admitted adapter; fatal UART evidence cannot become a valid sample."""
    if diagnostic_seconds is not None and (diagnostic_seconds <= 0 or evidence_directory is None):
        raise ValueError('diagnostic deadline requires a positive budget and separate evidence directory')
    stage = Path(stage)
    plan = json.loads((stage / 'plan.json').read_text())
    site = json.loads(Path(plan['platform']).read_text())
    child = subprocess.Popen(command, **(process_kwargs or {}))
    failed = False
    diagnostic_end = False
    started = time.monotonic()
    try:
        while child.poll() is None:
            time.sleep(interval)
            try:
                health = inspect(site, plan['name'])
            except (OSError, ValueError, subprocess.SubprocessError):
                continue  # a transient observer error must not kill a task
            if health.get('matching_driver_pids') and (health.get('kernel_panic') or health.get('simulation_failed')):
                stop_failed_guest(site, plan['name'], evidence_directory or stage / 'guest-failure-evidence')
                failed = True
                break
            if (diagnostic_seconds is not None and health.get('matching_driver_pids')
                    and time.monotonic() - started >= diagnostic_seconds):
                stop_diagnostic_guest(site, plan['name'], evidence_directory)
                diagnostic_end = True
                break
        rc = child.wait(timeout=180 if failed or diagnostic_end else None)
        if failed:
            raise GuestFailure('guest failed; archived UART and terminated its exact driver')
        if diagnostic_end:
            raise DiagnosticEnd('diagnostic host time budget reached; no performance result')
        if rc:
            raise subprocess.CalledProcessError(rc, command)
    finally:
        # Never cancel the manager and abandon an owned hardware task.
        if child.poll() is None:
            child.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', type=Path, required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        parser.error('a native adapter command is required')
    run(args.stage, command)


if __name__ == '__main__':
    main()
