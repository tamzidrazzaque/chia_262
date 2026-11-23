"""Exact-image replay is diagnostic-only and preserves all ordinary target knobs."""

import copy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from examples.rocket_cost_model.saturn_boot_replay import diagnostic_runtime
from examples.rocket_cost_model.saturn_spec.execution import guard
from examples.rocket_cost_model.saturn_spec.results import validate_completion


class BootReplayTests(unittest.TestCase):
    def test_only_diagnostic_trace_limit_and_suffix_change(self):
        original = {'tracing': {'enable': False}, 'target_config': {
            'plusarg_passthrough': '', 'default_hw_config': 'accepted'},
            'workload': {'workload_name': 'accepted.json', 'suffix_tag': 'old'},
            'host_debug': {'zero_out_dram': True}, 'run_farm': {'worker': 'accepted'}}
        saved = copy.deepcopy(original)
        result = diagnostic_runtime(original, 0x100, 0x120, 'new')
        self.assertNotIn('max-cycles', result['target_config']['plusarg_passthrough'])
        self.assertEqual(original, saved)
        result['tracing'] = original['tracing']
        result['target_config']['plusarg_passthrough'] = ''
        result['workload']['suffix_tag'] = 'old'
        self.assertEqual(result, original)
        self.assertEqual(diagnostic_runtime(original, 0x100, 0x120, 'new', trace=False)['tracing'], original['tracing'])
        raw = diagnostic_runtime(original, 0x100, 0x120, 'new', raw_trace=True)
        self.assertEqual(raw['target_config']['plusarg_passthrough'], '+trace-test-output')
        self.assertEqual(original, saved)
        with self.assertRaises(ValueError):
            diagnostic_runtime(original, 0x100, 0x120, 'new', trace=False, raw_trace=True)

    def test_replay_can_never_enter_performance_collector(self):
        with self.assertRaisesRegex(ValueError, 'diagnostic replays'):
            validate_completion({}, {}, {'diagnostic_replay': True}, {})

    def test_audit_must_be_separate_and_complete(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for kwargs in ({'diagnostic_audit': root},
                           {'diagnostic_audit': root, 'diagnostic_runtime': root / 'runtime.yaml'},
                           {'diagnostic_audit': root / 'new', 'diagnostic_runtime': root / 'runtime.yaml'}):
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                    with guard(root, 'infrasetup', **kwargs):
                        self.fail('invalid replay audit admitted')
