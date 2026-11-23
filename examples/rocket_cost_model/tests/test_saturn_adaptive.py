"""Adaptive transport contracts, with no model calls or FPGA dispatch."""

import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from examples.rocket_cost_model import saturn_adaptive_loop as loop
from examples.rocket_cost_model.saturn_bundle_artifact import SaturnBundle


class AdaptiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = {'remote_root': str(self.root / 'remote'), 'address': 'fixture',
            'task_root': 'fixture', 'manager_repo': 'fixture', 'manager_python': 'fixture',
            'policy': {'scope': 'test', 'worker_id': 'worker', 'platform_sha256': 'platform'},
            'baseline': {}}
        self.proposal = {'candidate_id': '3.2000', 'changes': {'int_stmt': 4}, 'rationale': 'fixture'}
        self.artifact = SaturnBundle(b'fixture', 'archive', 'manifest', 'executable')
        self.result = {'campaign_status': 'complete', 'proposal': self.proposal,
            'artifact': {'archive_sha256': 'archive', 'manifest_sha256': 'manifest', 'executable_sha256': 'executable'},
            'worker_id': 'worker', 'platform_sha256': 'platform',
            'feedback': {'candidates': [{'candidate_id': '3.2000', 'proposal': self.proposal}]}}

    def test_real_shell_delimiter_and_order_namespace(self):
        requests = []
        def ssh(config, command, **kwargs):
            if 'input' in kwargs:
                with tarfile.open(fileobj=io.BytesIO(kwargs['input'])) as archive:
                    requests.append(json.load(archive.extractfile('request.json')))
                dispatch = json.loads((self.root / 'dispatch.json').read_text())
                remote = Path(dispatch['remote_run'])
                remote.mkdir(parents=True)
                (remote / 'feedback.json').write_text(json.dumps(self.result))
            if kwargs.get('capture_output'):
                return subprocess.run(['bash', '-c', command], check=True, capture_output=True, text=True)
            return subprocess.CompletedProcess([], 0)
        with patch.object(loop, 'ssh', ssh):
            result = loop.measure(self.config, self.proposal, self.artifact, self.root, index=3)
        self.assertEqual(result, self.result)
        self.assertEqual(requests[0]['policy']['order_offset'], 3)
        self.assertEqual(requests[0]['policy']['sample_offset'], 100300)

    def test_wrong_feedback_target_or_artifact_rejected(self):
        for field, value in [('worker_id', 'other'), ('artifact', {}), ('proposal', {})]:
            with self.subTest(field=field):
                result = {**self.result, field: value}
                with self.assertRaises(ValueError):
                    loop.validate_feedback(result, self.proposal, self.artifact, self.config)

    def test_cost_changes_must_match_dispatched_candidate(self):
        self.result['feedback']['candidates'][0]['proposal'] = {'changes': {'int_stmt': 8}}
        with self.assertRaisesRegex(ValueError, 'cost profile'):
            loop.validate_feedback(self.result, self.proposal, self.artifact, self.config)

    def test_duplicate_proposal_receives_feedback_then_retries(self):
        seen = []
        def generate(payload):
            seen.append(payload)
            return {'changes': {'int_stmt': 4 if len(seen) == 1 else 12}, 'rationale': 'fixture'}
        rejections = []
        result = loop.choose_novel_proposal(generate, {},
            {loop.profile_signature({'int_stmt': 4})}, rejections)
        self.assertEqual(result['changes'], {'int_stmt': 12})
        self.assertEqual(len(rejections), 1)
        self.assertEqual(len(seen[1]['rejected_proposals']), 1)

    def test_proposal_retries_remain_bounded(self):
        rejected = []
        with self.assertRaisesRegex(ValueError, 'exhausted 3 attempts'):
            loop.choose_novel_proposal(lambda _: self.proposal, {},
                {loop.profile_signature({'int_stmt': 4})}, rejected)
        self.assertEqual(len(rejected), 3)
