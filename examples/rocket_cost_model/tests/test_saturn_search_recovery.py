"""Controller recovery and pre-dispatch identity checks; no target execution."""

import argparse
import fcntl
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from examples.rocket_cost_model import saturn_search_loop as loop


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.queue = root / 'queue'
        self.queue.mkdir()
        self.proposal = self.queue / '3.1.json'
        self.proposal.write_text(json.dumps({'candidate_id': '3.1'}))
        self.baseline = dict(platform_sha256='p', agfi='a', driver_sha256='d',
                             vlen_bits=256, input_id='mcf', cycles=100)
        baseline = root / 'baseline.json'
        baseline.write_text(json.dumps(self.baseline))
        self.state = root / 'state.json'
        self.work = root / 'work/3.1'
        self.args = argparse.Namespace(queue=self.queue, baseline=baseline, state=self.state,
            work_root=root / 'work', prepare_cmd='prepare', measure_cmd='measure', once=True, watch=False)

    def prepared(self):
        bundle = self.work / 'bundle/3-saturn-aware'
        bundle.mkdir(parents=True)
        (bundle / 'program').write_bytes(b'fixture')
        elf = loop._digest(bundle / 'program')
        (bundle / 'manifest.json').write_text(json.dumps({'executable': 'program', 'files_sha256': {'program': elf}}))
        metadata = {'executable_sha256': elf, 'bundle_sha256': loop._digest(bundle / 'manifest.json')}
        (self.work / 'candidate-metadata.json').write_text(json.dumps(metadata))
        return metadata

    def active(self, dispatch=False):
        self.work.mkdir(parents=True)
        record = {'candidate_id': '3.1', 'proposal_sha256': loop._digest(self.proposal),
                  'status': 'measuring' if dispatch else 'preparing', 'dispatch_started': dispatch}
        self.state.write_text(json.dumps({'baseline': self.baseline, 'candidates': [record]}))

    def test_active_state_is_visible_before_hook(self):
        def hook(*args):
            self.assertEqual(json.loads(self.state.read_text())['candidates'][0]['status'], 'preparing')
            raise RuntimeError('shared compiler infrastructure failed')
        with patch.object(loop, '_run_hook', hook), self.assertRaises(RuntimeError):
            loop.run(self.args)
        self.assertEqual(json.loads(self.state.read_text())['candidates'][0]['status'], 'blocked')

    def test_second_controller_is_refused_before_dispatch(self):
        lease_path = self.state.with_name(self.state.name + '.lock')
        with lease_path.open('a') as lease:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with patch.object(loop, '_run_hook') as hook, self.assertRaisesRegex(RuntimeError, 'another Saturn controller'):
                loop.run(self.args)
            hook.assert_not_called()
        # Releasing the first lease permits a new controller to acquire it.
        with patch.object(loop, '_run_locked') as run_locked:
            loop.run(self.args)
        run_locked.assert_called_once_with(self.args)

    def test_missing_metadata_never_dispatches(self):
        calls = []
        with patch.object(loop, '_run_hook', lambda *args: calls.append(args[-1])), self.assertRaises(RuntimeError):
            loop.run(self.args)
        self.assertEqual(calls, ['prepare'])

    def test_interrupted_measurement_never_redispatches(self):
        self.active(dispatch=True)
        self.prepared()
        with patch.object(loop, '_run_hook') as hook, self.assertRaises(RuntimeError):
            loop.run(self.args)
        hook.assert_not_called()

    def test_recovered_receipt_finishes_without_new_hardware(self):
        self.active(dispatch=True)
        metadata = self.prepared()
        receipt = {'status': 'correct', 'backend': 'fpga', 'identity': {**self.baseline, 'role': '3-saturn-aware',
                    'bundle_sha256': metadata['bundle_sha256']}, 'whole_boot_simulation_cycles': 90,
                    'executable_sha256': metadata['executable_sha256']}
        (self.work / 'candidate-receipt.json').write_text(json.dumps(receipt))
        with patch.object(loop, '_run_hook') as hook:
            loop.run(self.args)
        hook.assert_not_called()
        candidates = json.loads(self.state.read_text())['candidates']
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]['status'], 'complete')

    def test_tampered_bundle_blocks_resume(self):
        self.active()
        self.prepared()
        (self.work / 'bundle/3-saturn-aware/program').write_bytes(b'changed')
        with patch.object(loop, '_run_hook') as hook, self.assertRaises(ValueError):
            loop.run(self.args)
        hook.assert_not_called()

    def test_different_receipt_bundle_is_rejected(self):
        self.active(dispatch=True)
        metadata = self.prepared()
        receipt = {'status': 'correct', 'backend': 'fpga',
            'identity': {**self.baseline, 'role': '3-saturn-aware', 'bundle_sha256': 'f' * 64},
            'whole_boot_simulation_cycles': 90, 'executable_sha256': metadata['executable_sha256']}
        (self.work / 'candidate-receipt.json').write_text(json.dumps(receipt))
        with patch.object(loop, '_run_hook') as hook, self.assertRaises(ValueError):
            loop.run(self.args)
        hook.assert_not_called()
        self.assertEqual(json.loads(self.state.read_text())['candidates'][0]['status'], 'blocked')


if __name__ == '__main__':
    unittest.main()
