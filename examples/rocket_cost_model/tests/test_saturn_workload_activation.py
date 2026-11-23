"""Offline baseline activation gates; fixture cycles are never measurements."""

import json
from pathlib import Path
import subprocess
import tempfile
import signal
import unittest
from unittest.mock import patch

from examples.rocket_cost_model import saturn_activate_workload as activation
from examples.rocket_cost_model import saturn_workload_baselines as baselines
from examples.rocket_cost_model.spec_vector_baseline import publish_config


class ActivationTests(unittest.TestCase):
    def test_shared_spec_config_readers_never_observe_a_truncated_rewrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'shared.cfg'
            path.write_text('old complete config')
            with path.open() as reader:
                publish_config(path, 'new complete config')
                self.assertEqual(reader.read(), 'old complete config')
            self.assertEqual(path.read_text(), 'new complete config')
    def setUp(self):
        self.config = {'benchmark': '644.nab_s',
            'policy': {'worker_id': 'nab-worker', 'platform_sha256': 'nab-platform'},
            'activation_gate': {'expected_bundles': {'1-scalar': 'scalar', '2-generic-vector': 'vector'}}}
        self.status = {'status': 'complete', 'roles': []}
        for role, bundle in self.config['activation_gate']['expected_bundles'].items():
            self.status['roles'].append({'role': role, 'cycles': 100,
                'identity': {'role': role, 'bundle_sha256': bundle, 'phase': 'baseline',
                    'benchmark': '644.nab_s', 'input_id': 'nab-test',
                    **self.config['policy']}})

    def test_exact_second_worker_baselines_are_required(self):
        self.assertEqual(activation.validate_gate(self.status, self.config), 100)
        self.status['roles'][1]['identity']['worker_id'] = 'mcf-worker'
        with self.assertRaisesRegex(ValueError, 'worker/platform'):
            activation.validate_gate(self.status, self.config)

    def test_wrong_workload_or_bundle_cannot_unlock_optimization(self):
        for field in ('benchmark', 'bundle_sha256'):
            with self.subTest(field=field):
                status = json.loads(json.dumps(self.status))
                status['roles'][1]['identity'][field] = 'wrong'
                with self.assertRaises(ValueError):
                    activation.validate_gate(status, self.config)

    def test_failed_or_partial_gate_cannot_unlock(self):
        for value in ({'status': 'blocked'}, {'status': 'complete', 'roles': self.status['roles'][:1]}):
            with self.assertRaises(ValueError):
                activation.validate_gate(value, self.config)

    def test_status_transfer_uses_real_shell_and_tolerates_login_banner(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'baseline progress.json'
            config = {'activation_gate': {'progress': str(path)}}
            def ssh(config, command, **kwargs):
                result = subprocess.run(['bash', '-c', command], check=True, **kwargs)
                result.stdout = 'Agent pid 123\n' + result.stdout
                return result
            with patch.object(activation, 'ssh', ssh):
                self.assertEqual(activation.fetch_status(config), {'status': 'not_started'})
                path.write_text(json.dumps(self.status))
                self.assertEqual(activation.fetch_status(config), self.status)

    def test_coordinator_serializes_scalar_then_vector_in_same_lane(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            out = root / 'result'
            commands = []
            def run(command, **kwargs):
                commands.append(command)
                destination = Path(command[command.index('--out') + 1])
                destination.mkdir()
                role = destination.name
                entry = next(x for x in self.status['roles'] if x['role'] == role)
                (destination / 'receipt.json').write_text(json.dumps({
                    'status': 'correct', 'identity': entry['identity'], 'whole_boot_simulation_cycles': entry['cycles']}))
            argv = ['baselines', '--bundles', directory, '--lane', str(root / 'nab-lane'),
                '--address', 'nab-cluster', '--task-root', directory, '--out', str(out), '--first-attempt', '4000']
            with patch('sys.argv', argv), patch.object(baselines.subprocess, 'run', run):
                baselines.main()
            self.assertEqual(json.loads((out / 'progress.json').read_text())['status'], 'complete')
            self.assertEqual([x[x.index('--sample') + 1] for x in commands], ['0', '1'])
            self.assertTrue(all(x[x.index('--lane') + 1] == str(root / 'nab-lane') for x in commands))

    def test_stop_during_gate_fetch_never_launches_child(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'config.json'
            config.write_text(json.dumps(self.config))
            handlers = {}
            def register(sig, handler):
                handlers[sig] = handler
            def fetch(config):
                handlers[signal.SIGTERM]()
                return self.status
            argv = ['activate', '--config', str(config), '--out', str(root / 'out')]
            with patch('sys.argv', argv), patch.object(activation.signal, 'signal', register), \
                    patch.object(activation, 'fetch_status', fetch), \
                    patch.object(activation.subprocess, 'Popen') as launch:
                activation.main()
            launch.assert_not_called()
            self.assertEqual(json.loads((root / 'out/activation.json').read_text())['status'], 'drained')
