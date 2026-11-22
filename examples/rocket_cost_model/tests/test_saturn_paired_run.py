"""Admission tests for the pilot-gated paired CLI, using private-data-free fixtures."""

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from examples.rocket_cost_model.saturn_paired_run import validate_pilot, workload_identity


class PairedGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.source = Path(self.tmp.name)
        self.manifest = {'input_id': 'mcf-test', 'executable': 'program', 'files_sha256': {'program': 'elf'}}
        data = json.dumps(self.manifest).encode()
        (self.source / 'manifest.json').write_bytes(data)
        self.config = {'policy': {'scope': 'test', 'platform_sha256': 'platform', 'worker_id': 'worker'},
                       'candidates': [{'bundles': {'test': str(self.source)}}]}
        self.receipt = {'status': 'correct', 'backend': 'fpga', 'whole_boot_simulation_cycles': 10,
                        'executable_sha256': 'elf', 'identity': {'platform_sha256': 'platform',
                        'worker_id': 'worker', 'role': '3-saturn-aware', 'input_id': 'mcf-test',
                        'bundle_sha256': hashlib.sha256(data).hexdigest()}}

    def test_correct_pilot_is_admitted(self):
        validate_pilot(self.receipt, self.config)

    def test_other_worker_platform_role_or_bundle_is_rejected(self):
        for key in ('worker_id', 'platform_sha256', 'role', 'bundle_sha256', 'input_id'):
            receipt = json.loads(json.dumps(self.receipt))
            receipt['identity'][key] = 'unrelated'
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_pilot(receipt, self.config)

    def test_wrong_executable_and_missing_cycles_are_rejected(self):
        for key, value in [('executable_sha256', 'other'), ('whole_boot_simulation_cycles', None)]:
            receipt = dict(self.receipt)
            receipt[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_pilot(receipt, self.config)

    def test_workload_identity_changes_with_input_bytes(self):
        manifest = dict(size='test', input_id='input', argv=['./program'], stdin=None,
                        stdout='out', stderr='err', inputs={'input': 'payload/input'},
                        expected_outputs={'out': 'reference/out'},
                        files_sha256={'payload/input': 'a', 'reference/out': 'b'})
        original = workload_identity(manifest)
        manifest['files_sha256']['payload/input'] = 'changed'
        self.assertNotEqual(workload_identity(manifest), original)


if __name__ == '__main__':
    unittest.main()
