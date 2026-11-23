"""Read-only status tests use metadata fixtures, never hardware."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import subprocess

from examples.rocket_cost_model import saturn_status as s


class StatusTests(unittest.TestCase):
    def test_baseline_gate_visible_before_loop_exists(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'activation.json').write_text(json.dumps({
                'status': 'waiting_for_baselines', 'active_baseline_role': '1-scalar'}))
            text = s.summary('NAB', {'run': str(root / 'loop'), 'activation': str(root)})
            self.assertIn('waiting_for_baselines', text)
            self.assertIn('1-scalar', text)

    def test_local_snapshot_and_remote_failure_preserve_files(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            state = {'status': 'running', 'candidates': [
                {'candidate_id': '3.1', 'status': 'duplicate executable'},
                {'candidate_id': '3.2', 'status': 'complete', 'cycles': 90, 'baseline_cycles': 100},
                {'candidate_id': '3.3', 'status': 'measuring'}], 'measured_candidates': 1}
            (root / 'state.json').write_text(json.dumps(state))
            (root / '3.3').mkdir()
            (root / '3.3/dispatch.json').write_text('{"remote_run":"/private/run"}')
            (root / 'manager.json').write_text('{}')
            entry = {'run': str(root), 'manager_config': str(root / 'manager.json')}
            before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
            with patch.object(s, 'campaign_status') as remote:
                text = s.summary('NAB', entry, local_only=True)
                remote.assert_not_called()
            self.assertIn('duplicates skipped: 1', text)
            self.assertIn('+10.000% reduction', text)
            with patch.object(s, 'campaign_status', side_effect=subprocess.TimeoutExpired('ssh', 20)):
                self.assertIn('Manager status unavailable', s.summary('NAB', entry))
            with patch.object(s, 'campaign_status', return_value={
                    'status': 'running', 'guest_health': {'health': 'FAILED: guest kernel panic'}}):
                self.assertIn('GUEST FAILED', s.summary('NAB', entry).splitlines()[0])
            self.assertEqual(before, {p: p.read_bytes() for p in root.rglob('*') if p.is_file()})

    def test_manager_reads_only_dispatched_campaign_and_tolerates_banner(self):
        response = subprocess.CompletedProcess([], 0, 'Agent pid 123\nSATURN_STATUS:{"status":"running"}\n')
        with patch.object(s.subprocess, 'run', return_value=response) as run:
            result = s.campaign_status({'manager_key': '/private/key', 'manager_host': 'user@host',
                'manager_repo': '/repo', 'manager_python': '/python'}, '/private/run')
        self.assertEqual(result['status'], 'running')
        self.assertIn('StrictHostKeyChecking=yes', run.call_args.args[0])
        command = run.call_args.args[0][-1]
        self.assertIn('--campaign /private/run', command)
        self.assertIn('saturn_guest_health', command)
        self.assertNotIn('write_text', command)
