"""Run the diagnostic launcher against real child processes without FPGA access."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(shutil.which('cc'), 'native C compiler required')
class NabRepeatTests(unittest.TestCase):
    def test_repeat_preserves_argv_and_keeps_outputs_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'hkrdenq').mkdir()
            (root / 'hkrdenq/input').write_text('unchanged input')
            launcher = root / 'launcher'
            source = Path(__file__).parents[1] / 'saturn_spec/nab_repeat.c'
            subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', str(source), '-o', str(launcher)], check=True)
            env = {**os.environ, 'SATURN_NAB_DIAGNOSTIC_MODES': 'normal,normal'}
            result = subprocess.run([str(launcher), str(root), '/bin/printf', '%s\n', 'argument with spaces'],
                                    env=env, cwd=root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            for i in range(2):
                out = root / 'repetitions' / f'{i}-normal'
                self.assertEqual((out / 'stdout.txt').read_text(), 'argument with spaces\n')
                self.assertTrue((out / 'exec-maps.txt').read_text())
                self.assertEqual((out / 'hkrdenq/input').read_text(), 'unchanged input')
                self.assertEqual(json.loads((out / 'status.json').read_text())['exit_code'], 0)
            retry = subprocess.run([str(launcher), str(root), '/bin/true'], env=env, capture_output=True)
            self.assertEqual(retry.returncode, 125)
            self.assertEqual((root / 'repetitions/0-normal/stdout.txt').read_text(), 'argument with spaces\n')

    def test_child_failure_and_bad_modes_never_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'hkrdenq').mkdir()
            launcher = root / 'launcher'
            source = Path(__file__).parents[1] / 'saturn_spec/nab_repeat.c'
            subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', str(source), '-o', str(launcher)], check=True)
            env = {**os.environ, 'SATURN_NAB_DIAGNOSTIC_MODES': 'normal'}
            result = subprocess.run([str(launcher), str(root), '/bin/sh', '-c', 'exit 7'], env=env, cwd=root, capture_output=True)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads((root / 'repetitions/0-normal/status.json').read_text())['exit_code'], 7)
            for mode in ('', 'unknown', ','.join(['normal'] * 9)):
                with self.subTest(mode=mode):
                    result = subprocess.run([str(launcher), str(root), '/bin/true'],
                        env={**env, 'SATURN_NAB_DIAGNOSTIC_MODES': mode}, capture_output=True)
                    self.assertEqual(result.returncode, 125)
