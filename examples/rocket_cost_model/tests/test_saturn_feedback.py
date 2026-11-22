"""Measured feedback tests do not launch an LLM or read private artifacts."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from examples.rocket_cost_model.saturn_feedback_proposer import propose


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.queue = Path(self.temp.name)
        self.state = {'baseline': {'cycles': 100}, 'candidates': [
            {'candidate_id': '3.2', 'status': 'complete', 'cycles': 90,
             'proposal': {'changes': {'int_stmt': 4}},
             'private_log': 'must never enter prompt'}]}

    def test_measured_feedback_reaches_model_and_is_bounded(self):
        memory = {}
        seen = []
        def generate(payload, model):
            seen.append(payload)
            return {'changes': {'int_stmt': 6}, 'rationale': 'Test measured threshold'}
        self.assertTrue(propose(self.queue, self.state, memory, 4, generate, budget=1))
        self.assertEqual(seen[0]['measured_history'], [{'changes': {'int_stmt': 4}, 'cycles': 90}])
        self.assertNotIn('must never enter prompt', json.dumps(seen))
        self.assertFalse(propose(self.queue, self.state, memory, 4, generate, budget=1))
        self.assertEqual(len(seen), 1)

    def test_incomplete_manual_record_never_calls_model(self):
        del self.state['candidates'][0]['cycles']
        def forbidden(*args):
            self.fail('model called without measured cycles')
        self.assertFalse(propose(self.queue, self.state, {}, 4, forbidden))

    def test_invalid_model_output_never_publishes(self):
        def generate(*args):
            return {'changes': {'int_stmt': 100}, 'rationale': 'invalid'}
        with self.assertRaises(ValueError):
            propose(self.queue, self.state, {}, 4, generate)
        self.assertEqual(list(self.queue.glob('*.json')), [])

    def test_duplicate_model_output_never_publishes(self):
        (self.queue / '3.2.json').write_text(json.dumps({
            'candidate_id': '3.2', 'changes': {'int_stmt': 4}}))
        def generate(*args):
            return {'changes': {'int_stmt': 4}, 'rationale': 'duplicate'}
        with self.assertRaisesRegex(ValueError, 'repeated'):
            propose(self.queue, self.state, {}, 4, generate)


if __name__ == '__main__':
    unittest.main()
