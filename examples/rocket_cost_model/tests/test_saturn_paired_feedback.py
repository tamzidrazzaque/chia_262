"""Only verified, non-holdout paired receipts feed feedback proposals."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from examples.rocket_cost_model.saturn_feedback_proposer import paired_feedback_state, measured_history


class PairedFeedbackTests(unittest.TestCase):
    def fixture(self, root, phase='search'):
        profiles = root / 'profiles'
        profiles.mkdir()
        (profiles / '3.10.json').write_text(json.dumps({'candidate_id': '3.10',
            'changes': {'int_stmt': 8}, 'rationale': 'fixture cost proposal'}))
        history = [{'status': 'measured', 'proposal': {'candidate_id': '3.10'},
                    'candidate': {'bundle_sha256': 'candidate-bundle'}}]
        samples = []
        for number, (role, cycles, bundle) in enumerate([
                ('2-generic-vector', 100, 'baseline-bundle'), ('3-saturn-aware', 110, 'candidate-bundle')]):
            receipt = {'status': 'correct', 'backend': 'fpga', 'whole_boot_simulation_cycles': cycles,
                'identity': {'role': role, 'bundle_sha256': bundle, 'worker_id': 'worker',
                             'platform_sha256': 'platform', 'input_id': 'input', 'phase': phase}}
            name = f'receipt-{number}.json'
            (root / name).write_text(json.dumps(receipt))
            checksum = hashlib.sha256(json.dumps(receipt, sort_keys=True).encode()).hexdigest()
            samples.append({'receipt': name, 'receipt_sha256': checksum, 'cycles': cycles})
        (root / 'progress.json').write_text(json.dumps({'history': history, 'samples': samples}))
        return profiles

    def test_regression_and_fresh_baseline_reach_model_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profiles = self.fixture(root)
            state = paired_feedback_state(root, profiles)
            self.assertEqual(measured_history(state), [
                {'changes': {'int_stmt': 8}, 'cycles': 110, 'baseline_cycles': 100}])

    def test_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profiles = self.fixture(root)
            (root / 'receipt-1.json').write_text('{}')
            with self.assertRaises(ValueError):
                paired_feedback_state(root, profiles)

    def test_holdout_never_enters_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profiles = self.fixture(root, 'holdout')
            self.assertEqual(paired_feedback_state(root, profiles)['candidates'], [])
