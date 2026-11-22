"""Worker admission tests run without a Ray cluster or hardware."""

import importlib.util
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


def load_bridge():
    stub = types.ModuleType('chia.base.ChiaFunction')
    stub.ChiaFunction = lambda **kwargs: lambda fn: fn
    stub.get = lambda value: value
    spec = importlib.util.spec_from_file_location('bridge_under_test',
        Path(__file__).parents[1] / 'saturn_chia_tasks.py')
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'chia.base.ChiaFunction': stub}):
        spec.loader.exec_module(module)
    return module


class WorkerAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.bridge = load_bridge()

    def test_resource_missing_fails_before_dispatch(self):
        with self.assertRaisesRegex(RuntimeError, 'no live'):
            self.bridge.select_worker([], 'saturn_manager')

    def test_task_timeout_drains_same_reference_without_redispatch(self):
        class Timeout(Exception):
            pass
        calls = []
        reference = object()
        def get(ref, **kwargs):
            calls.append((ref, kwargs))
            if kwargs:
                raise Timeout()
            return {'status': 'correct'}
        stub = types.SimpleNamespace(get=get, exceptions=types.SimpleNamespace(GetTimeoutError=Timeout))
        with patch.dict(sys.modules, {'ray': stub}):
            result = self.bridge.await_task(reference, 1)
        self.assertEqual(result, {'status': 'correct'})
        self.assertEqual(calls, [(reference, {'timeout': 1}), (reference, {})])

    def test_manager_resource_requires_singleton(self):
        node = {'Alive': True, 'Resources': {'saturn_manager': 1}, 'NodeID': 'one'}
        self.assertEqual(self.bridge.select_worker([node], 'saturn_manager'), 'one')
        for nodes in ([node, {**node, 'NodeID': 'two'}],
                      [{**node, 'Resources': {'saturn_manager': 2}}]):
            with self.assertRaisesRegex(RuntimeError, 'exactly one'):
                self.bridge.select_worker(nodes, 'saturn_manager')

    def test_mount_mismatch_blocks_preparation(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'marker'
            path.write_bytes(b'controller')
            with self.assertRaisesRegex(RuntimeError, 'mount differs'):
                self.bridge.verify_worker('prepare', str(path), '0' * 64, str(path), '0' * 64)

    def test_manager_configuration_checked_without_key_contents(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'marker'
            path.write_bytes(b'mount')
            digest = hashlib.sha256(b'mount').hexdigest()
            env = {'SATURN_MANAGER_HOST': 'fixture', 'SATURN_MANAGER_KEY': str(path)}
            with patch.dict(os.environ, env, clear=True):
                result = self.bridge.verify_worker('measure', str(path), digest, str(path), digest)
            self.assertTrue(result['mounts_verified'])

    def test_existing_role_graph_accepts_mcf_screen(self):
        stub = types.ModuleType('chia.base.ChiaFunction')
        stub.ChiaFunction = lambda **kwargs: lambda fn: fn
        stub.get = lambda value: value
        spec = importlib.util.spec_from_file_location('roles_under_test',
            Path(__file__).parents[1] / 'roles_123_chia.py')
        roles = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'chia.base.ChiaFunction': stub, 'ray': types.ModuleType('ray')}):
            spec.loader.exec_module(roles)
        with tempfile.TemporaryDirectory() as root:
            label = roles.role_settings('2-generic-vector')[0]
            (Path(root) / f'605.mcf_s-test-{label}-validate.log').write_text(
                ' Success 605.mcf_s base test fixture\n')
            result = types.SimpleNamespace(returncode=0)
            with patch.object(roles.subprocess, 'run', return_value=result), \
                 patch.object(roles, '_audit_elf', return_value={'static_rvv_instruction_count': 4}):
                record = roles.run_role_task(root, root, root, root, root, root,
                    root, '2-generic-vector', '605.mcf_s', 'test')
            self.assertTrue(record['validated'])
            self.assertEqual(record['output_validation']['validator'], 'spec-success-line-only')
            self.assertFalse(record['target_performance_result'])


if __name__ == '__main__':
    unittest.main()
