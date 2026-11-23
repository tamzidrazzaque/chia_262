"""Pilot gate and terminal publication tests without hardware."""

import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from examples.rocket_cost_model import saturn_artifact_pilot as pilot
from examples.rocket_cost_model.saturn_paired_run import wait_for_pilot


class PilotLifecycleTests(unittest.TestCase):
    def test_failure_stops_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'failed.json').write_text('{}')
            with self.assertRaisesRegex(RuntimeError, 'pilot failed'):
                wait_for_pilot(root / 'receipt.json', {}, threading.Event(), interval=0)

    def test_incomplete_receipt_cannot_open_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'receipt.json').write_text('{')
            with self.assertRaises(TimeoutError):
                wait_for_pilot(root / 'receipt.json', {}, threading.Event(), timeout=0)

    def test_terminal_error_is_published(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / 'attempt'
            argv = ['pilot', '--bundle', directory, '--candidate', '3.1', '--address', 'fixture',
                    '--task-root', directory, '--out', str(out)]
            with patch('sys.argv', argv), patch.object(pilot, 'execute', side_effect=RuntimeError('fixture failure')):
                with self.assertRaises(RuntimeError):
                    pilot.main()
            self.assertEqual(json.loads((out / 'failed.json').read_text())['status'], 'failed')
            self.assertFalse((out / 'receipt.json').exists())
