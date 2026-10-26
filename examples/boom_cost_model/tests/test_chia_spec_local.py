"""Ensure CHIA's SPEC node requires an explicit correctness result."""

import importlib.util
from pathlib import Path
import sys
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "chia_spec_local.py"


class TestValidation(unittest.TestCase):
    def test_success_must_match_benchmark_and_input(self):
        try:
            import ray  # noqa: F401
        except ImportError:
            self.skipTest("CHIA's Ray environment is not active")
        sys.path.insert(0, str(SOURCE.parent))
        spec = importlib.util.spec_from_file_location("chia_spec_local", SOURCE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        output = " Success 505.mcf_r base test ratio=-0.00, runtime=25.0\n"
        self.assertTrue(module.validated(output, "505.mcf_r", "test"))
        self.assertFalse(module.validated(output, "531.deepsjeng_r", "test"))
        self.assertFalse(module.validated(output, "505.mcf_r", "train"))


if __name__ == "__main__":
    unittest.main()
