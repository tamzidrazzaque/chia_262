"""Check that the private SPEC configuration pins the experiment variables."""

import importlib.util
from pathlib import Path
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "spec_cpu2017_local.py"
SPEC = importlib.util.spec_from_file_location("spec_cpu2017_local", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class TestConfig(unittest.TestCase):
    def test_real_speckle_template_pins_isa_abi_and_each_compiler(self):
        template = (SOURCE.parents[2].parent / "chipyard-boom-cost/software/spec2017/speckle/riscv.cfg")
        if not template.is_file():
            self.skipTest("Isolated Chipyard checkout not present")
        for tune in MODULE.TUNES:
            with self.subTest(tune=tune):
                config = MODULE.render_config(template.read_text(), tune, Path("/tmp/qemu-riscv64"))
                self.assertIn("-march=rv64gc -mabi=lp64d", config)
                self.assertEqual(config.count(f"-mtune={tune}"), 3)
                self.assertIn("submit = /tmp/qemu-riscv64 ${command}", config)
                self.assertIn(f"%define label riscv_{tune.replace('-', '_')}", config)

    def test_rejects_unexpected_template_and_qemu_path(self):
        with self.assertRaises(ValueError):
            MODULE.render_config("unexpected", "rocket", Path("/tmp/qemu"))
        with self.assertRaises(ValueError):
            MODULE.render_config("unexpected", "rocket", Path("relative-qemu"))

    def test_validation_requires_matching_spec_success(self):
        log = " Success 505.mcf_r base test ratio=-0.00, runtime=25.0\n"
        self.assertTrue(MODULE.validated(log, "505.mcf_r", "test"))
        self.assertFalse(MODULE.validated(log, "505.mcf_r", "train"))
        self.assertFalse(MODULE.validated(log, "531.deepsjeng_r", "test"))
        self.assertFalse(MODULE.validated("Failure 505.mcf_r base test\n", "505.mcf_r", "test"))


if __name__ == "__main__":
    unittest.main()
