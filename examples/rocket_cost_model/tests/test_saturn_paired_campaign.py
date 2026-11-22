"""Offline control-flow tests; fixture receipts are not hardware evidence."""

from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest

from examples.rocket_cost_model.saturn_paired_campaign import Policy, run


class CampaignTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.policy = Policy('worker', 'platform', {'agfi': 'fixture'}, 'runtime',
                             confirm_repeats=2, min_improvement=.02)
        self.calls = []

    def prepare(self, proposal, scope, directory):
        directory.mkdir()
        name = 'base' if proposal is None else str(proposal['cost'])
        return {'role': '2-generic-vector' if proposal is None else '3-saturn-aware',
                'scope': scope, 'bundle_sha256': scope + name, 'executable_sha256': name,
                'input_id': 'input-' + scope, 'workload_sha256': 'workload-' + scope,
                'fingerprint': {'filesystem': {'sha256': scope + name}}}

    def measure(self, artifact, request, directory):
        self.calls.append((artifact['role'], request['phase'], artifact['scope']))
        return {'status': 'correct', 'backend': 'fpga', 'identity': {
            'worker_id': 'worker', 'platform_sha256': 'platform',
            'bundle_sha256': artifact['bundle_sha256'], 'input_id': artifact['input_id'],
            'role': artifact['role'], 'phase': request['phase'], 'sample': request['sample']},
            'executable_sha256': artifact['executable_sha256'],
            'whole_boot_simulation_cycles': 100 if artifact['role'] == '2-generic-vector' else 90}

    def test_fresh_pairs_confirmation_holdout_and_recovery(self):
        state = run(self.root, [{'cost': 4}], self.policy, self.prepare, self.measure)
        self.assertEqual(state['status'], 'complete')
        self.assertEqual(len(state['samples']), 8)  # pilot, two confirmation pairs, ref
        self.assertEqual(len({s['measurement_key'] for s in state['samples']}), 8)
        roles = [role for role, phase, scope in self.calls]
        self.assertEqual(roles[:6], ['2-generic-vector', '3-saturn-aware',
            '3-saturn-aware', '2-generic-vector', '2-generic-vector', '3-saturn-aware'])
        self.assertEqual(self.calls[-1][2], 'ref')
        count = len(self.calls)
        run(self.root, [{'cost': 4}], self.policy, self.prepare, self.measure)
        self.assertEqual(len(self.calls), count)

    def test_next_preparation_overlaps_measurement(self):
        next_ready = threading.Event()
        def prepare(proposal, scope, directory):
            result = self.prepare(proposal, scope, directory)
            if proposal == {'cost': 8}:
                next_ready.set()
            return result
        def measure(artifact, request, directory):
            self.assertTrue(next_ready.wait(2))
            return self.measure(artifact, request, directory)
        state = run(self.root, [{'cost': 4}, {'cost': 8}], self.policy, prepare, measure)
        self.assertEqual(state['status'], 'complete')

    def test_wrong_physical_worker_blocks_campaign(self):
        def wrong(artifact, request, directory):
            receipt = self.measure(artifact, request, directory)
            receipt['identity']['worker_id'] = 'other-worker'
            return receipt
        with self.assertRaisesRegex(ValueError, 'identity mismatch'):
            run(self.root, [{'cost': 4}], self.policy, self.prepare, wrong)
        with self.assertRaisesRegex(RuntimeError, 'receipt recovery'):
            run(self.root, [{'cost': 4}], self.policy, self.prepare, self.measure)

    def test_paired_input_bytes_must_match_even_with_same_input_id(self):
        def prepare(proposal, scope, directory):
            artifact = self.prepare(proposal, scope, directory)
            if proposal is not None:
                artifact['workload_sha256'] = 'different-input-bytes'
            return artifact
        with self.assertRaisesRegex(ValueError, 'input/reference bytes differ'):
            run(self.root, [{'cost': 4}], self.policy, prepare, self.measure)
        self.assertEqual(self.calls, [])

    def test_stop_drains_and_prevents_measurement(self):
        stop = threading.Event()
        def prepare(proposal, scope, directory):
            artifact = self.prepare(proposal, scope, directory)
            if proposal is not None:
                stop.set()
            return artifact
        state = run(self.root, [{'cost': 4}], self.policy, prepare, self.measure, stop)
        self.assertEqual(state['status'], 'drained')
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
