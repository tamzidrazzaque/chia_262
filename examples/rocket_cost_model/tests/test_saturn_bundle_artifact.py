"""Private artifact transport tests; fixture bytes are never executed."""

from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from examples.rocket_cost_model.saturn_bundle_artifact import pack, unpack, digest
from examples.rocket_cost_model.tests.test_saturn_chia_bridge import load_bridge


class BundleTransportTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.bundle = self.root / 'source'
        (self.bundle / 'payload').mkdir(parents=True)
        program = b'unit fixture bytes, never run'
        (self.bundle / 'payload/program').write_bytes(program)
        manifest = {'role': '3-saturn-aware', 'executable': 'payload/program',
                    'files_sha256': {'payload/program': digest(program)}}
        (self.bundle / 'manifest.json').write_text(json.dumps(manifest))
        self.artifact = pack(self.bundle)

    def test_roundtrip_bound_bytes_and_executable_mode(self):
        destination = self.root / 'received'
        metadata = unpack(self.artifact, destination)
        self.assertEqual((destination / 'payload/program').read_bytes(),
                         (self.bundle / 'payload/program').read_bytes())
        self.assertEqual(metadata['bundle_sha256'], self.artifact.manifest_sha256)
        self.assertTrue((destination / 'payload/program').stat().st_mode & 0o100)
        self.assertNotIn('unit fixture', repr(self.artifact))

    def test_tampered_archive_rejected_before_writing(self):
        changed = replace(self.artifact, archive=self.artifact.archive + b'x')
        with self.assertRaisesRegex(ValueError, 'archive changed'):
            unpack(changed, self.root / 'received')
        self.assertFalse((self.root / 'received').exists())

    def test_symlink_and_escape_members_rejected_even_if_transport_hash_matches(self):
        for name, kind in (('../escape', tarfile.REGTYPE), ('link', tarfile.SYMTYPE)):
            data = io.BytesIO()
            with tarfile.open(fileobj=data, mode='w:') as archive:
                item = tarfile.TarInfo(name)
                item.type = kind
                item.linkname = '/etc/passwd' if kind == tarfile.SYMTYPE else ''
                archive.addfile(item)
            changed = replace(self.artifact, archive=data.getvalue(), archive_sha256=digest(data.getvalue()))
            with self.assertRaisesRegex(ValueError, 'unsafe'):
                unpack(changed, self.root / 'received')

    def test_manager_artifact_dryrun_uses_worker_local_scratch(self):
        bridge = load_bridge()
        with patch.dict(bridge.os.environ, {'SATURN_TASK_ROOT': str(self.root / 'manager')}):
            metadata = bridge.validate_artifact(self.artifact)
        self.assertEqual(metadata['bundle_sha256'], self.artifact.manifest_sha256)
        self.assertEqual(len(list((self.root / 'manager').glob('saturn-task-*'))), 1)

    def test_manager_receipt_must_bind_transported_artifact(self):
        bridge = load_bridge()
        def invoke(module, candidate, work, proposal, extra_environment):
            self.assertEqual(extra_environment, {'SATURN_MANAGER_LOCAL': '1', 'SATURN_ROLE': '3-saturn-aware'})
            receipt = {'executable_sha256': '0' * 64,
                       'identity': {'bundle_sha256': self.artifact.manifest_sha256}}
            (Path(work) / 'candidate-receipt.json').write_text(json.dumps(receipt))
        with patch.dict(bridge.os.environ, {'SATURN_TASK_ROOT': str(self.root / 'manager')}), \
                patch.object(bridge, 'invoke', invoke):
            with self.assertRaisesRegex(ValueError, 'receipt differs'):
                bridge.measure_artifact('3.99', self.artifact)

    def test_vector_baseline_receives_role_specific_directory_and_manager_environment(self):
        path = self.bundle / 'manifest.json'
        manifest = json.loads(path.read_text())
        manifest['role'] = '2-generic-vector'
        path.write_text(json.dumps(manifest))
        baseline = pack(self.bundle)
        bridge = load_bridge()
        def invoke(module, candidate, work, proposal, extra_environment):
            self.assertEqual(extra_environment, {'SATURN_MANAGER_LOCAL': '1', 'SATURN_ROLE': '2-generic-vector'})
            self.assertTrue((Path(work) / 'bundle/2-generic-vector/manifest.json').is_file())
            receipt = {'executable_sha256': baseline.executable_sha256,
                       'identity': {'role': '2-generic-vector', 'bundle_sha256': baseline.manifest_sha256}}
            (Path(work) / 'candidate-receipt.json').write_text(json.dumps(receipt))
        with patch.dict(bridge.os.environ, {'SATURN_TASK_ROOT': str(self.root / 'manager')}), \
                patch.object(bridge, 'invoke', invoke):
            receipt = bridge.measure_artifact('3.99', baseline)
        self.assertEqual(receipt['identity']['role'], '2-generic-vector')


if __name__ == '__main__':
    unittest.main()
