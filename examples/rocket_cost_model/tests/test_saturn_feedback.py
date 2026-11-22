"""Measured feedback tests do not launch an LLM or read private artifacts."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from examples.rocket_cost_model.saturn_feedback_proposer import propose
from examples.rocket_cost_model import saturn_feedback_proposer as feedback


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

    def test_crash_after_publication_does_not_republish_source(self):
        def generate(*args):
            return {'changes': {'int_stmt': 6}, 'rationale': 'measured feedback'}
        # Simulate loss of all in-memory state after queue publication, before
        # main() persists its separate --memory file.
        self.assertTrue(propose(self.queue, self.state, {}, 4, generate))
        with patch.object(feedback, 'codex_proposal') as model:
            self.assertFalse(propose(self.queue, self.state, {}, 4, model))
            model.assert_not_called()
        self.assertEqual(len(list(self.queue.glob('*.json'))), 1)

    def test_crash_after_reservation_preserves_budget_and_source(self):
        real_publish = feedback.publish_json
        def crash_on_proposal(path, value):
            if path.suffix == '.json':
                raise RuntimeError('simulated crash before proposal publication')
            real_publish(path, value)
        def generate(*args):
            return {'changes': {'int_stmt': 6}, 'rationale': 'measured feedback'}
        with patch.object(feedback, 'publish_json', crash_on_proposal):
            with self.assertRaisesRegex(RuntimeError, 'simulated crash'):
                propose(self.queue, self.state, {}, 4, generate, budget=1)
        with patch.object(feedback, 'codex_proposal') as model:
            self.assertFalse(propose(self.queue, self.state, {}, 4, model, budget=1))
            model.assert_not_called()
        self.assertEqual(list(self.queue.glob('*.json')), [])

    def test_journal_reserves_budget_across_distinct_sources(self):
        def generate(*args):
            return {'changes': {'int_stmt': 6}, 'rationale': 'measured feedback'}
        self.assertTrue(propose(self.queue, self.state, {}, 4, generate, budget=1))
        self.state['candidates'].append({'candidate_id': '3.4', 'status': 'complete',
            'cycles': 80, 'proposal': {'changes': {'int_stmt': 6}}})
        with patch.object(feedback, 'codex_proposal') as model:
            self.assertFalse(propose(self.queue, self.state, {}, 4, model, budget=1))
            model.assert_not_called()

    def test_concurrent_proposers_publish_once(self):
        start = Barrier(2)
        calls = []
        def generate(*args):
            calls.append(1)
            return {'changes': {'int_stmt': 6}, 'rationale': 'measured feedback'}
        def worker():
            start.wait(timeout=5)
            return propose(self.queue, self.state, {}, 4, generate)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: worker(), range(2)))
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(list(self.queue.glob('*.json'))), 1)


if __name__ == '__main__':
    unittest.main()
