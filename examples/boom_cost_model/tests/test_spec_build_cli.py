"""Verify the SPEC build CLI forwards tuning flags to the CHIA workload."""

import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock


SOURCE = Path(__file__).resolve().parents[2] / "spec_build/spec_sw_build_loop.py"


class TestSpecBuildCLI(unittest.TestCase):
    def test_spec_flags_reach_start_workload(self):
        try:
            import ray  # noqa: F401
        except ImportError:
            self.skipTest("CHIA's Ray environment is not active")
        spec = importlib.util.spec_from_file_location("spec_sw_build_loop", SOURCE)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        workload = mock.Mock(success=True, archive=b"archive", json_name="spec.json")
        flags = "-O3 -march=rv64gc -mabi=lp64d -mtune=generic-ooo"
        with mock.patch.object(sys, "argv", ["spec_sw_build_loop.py", "spec17-intrate-test",
                                              "--spec-flags", flags]), \
             mock.patch.object(module.ray, "init"), \
             mock.patch.object(module, "start_workload", return_value="ref") as start, \
             mock.patch.object(module, "get", return_value=workload):
            self.assertEqual(module.main(), 0)
        start.assert_called_once_with("spec17-intrate-test", spec_flags=flags)


if __name__ == "__main__":
    unittest.main()
