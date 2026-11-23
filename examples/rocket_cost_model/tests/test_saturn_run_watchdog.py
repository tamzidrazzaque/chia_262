"""Failed-guest recovery preserves evidence and never mistakes silence for failure."""

import base64
import json
from pathlib import Path
import subprocess
import shlex
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

from examples.rocket_cost_model import saturn_run_watchdog as w
from examples.rocket_cost_model import saturn_guest_health as h


class WatchdogTests(unittest.TestCase):
    def test_explicit_diagnostic_deadline_is_separate_from_fatal_guest(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'platform.json').write_text('{}')
            (root / 'plan.json').write_text(json.dumps({'platform': str(root / 'platform.json'), 'name': 'job'}))
            child = MagicMock(); child.poll.side_effect = [None, 0]; child.wait.return_value = 0
            with patch.object(w.subprocess, 'Popen', return_value=child), \
                 patch.object(w.time, 'sleep'), patch.object(w.time, 'monotonic', side_effect=[0, 301]), \
                 patch.object(w, 'inspect', return_value={'matching_driver_pids': [42]}), \
                 patch.object(w, 'stop_failed_guest') as fatal, \
                 patch.object(w, 'stop_diagnostic_guest') as diagnostic:
                with self.assertRaises(w.DiagnosticEnd):
                    w.run(root, ['native'], evidence_directory=root / 'diagnostic', diagnostic_seconds=300)
                fatal.assert_not_called(); diagnostic.assert_called_once_with({}, 'job', root / 'diagnostic')

    def test_fatal_evidence_archived_before_signal(self):
        with TemporaryDirectory() as directory:
            destination = Path(directory) / 'evidence'
            site = {'ssh_key': '/key', 'known_hosts': '/hosts', 'worker_ip': 'worker',
                    'artifacts': {'driver': {'sha256': 'a' * 64}}}
            evidence = {'pid': 42, 'job': 'job', 'uart': base64.b64encode(b'Kernel panic').decode()}
            def ssh(args, **kwargs):
                if destination.exists():
                    self.assertEqual((destination / 'uartlog').read_bytes(), b'Kernel panic')
                    self.assertIn("kill','-TERM'", shlex.split(args[-1])[4])
                return subprocess.CompletedProcess(args, 0, json.dumps(evidence))
            with patch.object(h.subprocess, 'run', side_effect=ssh) as calls:
                h.stop_failed_guest(site, 'job', destination)
            self.assertEqual(calls.call_count, 2)

    def test_snapshot_failure_cannot_signal(self):
        with TemporaryDirectory() as directory:
            site = {'ssh_key': '/key', 'known_hosts': '/hosts', 'worker_ip': 'worker',
                    'artifacts': {'driver': {'sha256': 'a' * 64}}}
            with patch.object(h.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'ssh')) as calls:
                with self.assertRaises(subprocess.CalledProcessError):
                    h.stop_failed_guest(site, 'job', Path(directory) / 'evidence')
            self.assertEqual(calls.call_count, 1)

    def test_quiet_guest_not_stopped_and_panic_cannot_pass(self):
        for panic in (False, True):
            with self.subTest(panic=panic), TemporaryDirectory() as directory:
                root = Path(directory)
                (root / 'platform.json').write_text('{}')
                (root / 'plan.json').write_text(json.dumps({'platform': str(root / 'platform.json'), 'name': 'job'}))
                child = MagicMock(); child.poll.side_effect = [None, 0, 0]; child.wait.return_value = 0
                with patch.object(w.subprocess, 'Popen', return_value=child) as spawn, \
                     patch.object(w.time, 'sleep'), \
                     patch.object(w, 'inspect', return_value={'matching_driver_pids': [42], 'kernel_panic': panic, 'uart_age_seconds': 9999}), \
                     patch.object(w, 'stop_failed_guest') as stop:
                    if panic:
                        with self.assertRaisesRegex(RuntimeError, 'guest failed'):
                            w.run(root, ['native-manager'], evidence_directory=root / 'diagnostic-evidence',
                                  process_kwargs={'env': {'FIXTURE': '1'}})
                        stop.assert_called_once()
                        self.assertEqual(stop.call_args.args[-1], root / 'diagnostic-evidence')
                        spawn.assert_called_once_with(['native-manager'], env={'FIXTURE': '1'})
                    else:
                        w.run(root, ['native-manager'])
                        stop.assert_not_called()
