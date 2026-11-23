"""Evidence-preserving sparse image maintenance on temporary fixture files."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from examples.rocket_cost_model.saturn_space import SCRIPT


class SpaceTests(unittest.TestCase):
    def test_compaction_preserves_every_byte(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'fixture.img'
            data = b'fixture' + bytes(1024 * 1024)
            path.write_bytes(data)
            result = subprocess.run([sys.executable, '-c', SCRIPT,
                json.dumps({'root': str(root), 'paths': [str(path)]})],
                text=True, capture_output=True, check=True)
            self.assertEqual(path.read_bytes(), data)
            record = json.loads(result.stdout)
            self.assertEqual(record['images'][0]['sha256'], hashlib.sha256(data).hexdigest())

    def test_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'target.img'
            target.write_bytes(b'fixture')
            link = root / 'link.img'
            link.symlink_to(target)
            result = subprocess.run([sys.executable, '-c', SCRIPT,
                json.dumps({'root': str(root), 'paths': [str(link)]})],
                text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(target.read_bytes(), b'fixture')
