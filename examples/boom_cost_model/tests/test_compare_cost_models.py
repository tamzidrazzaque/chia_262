"""Check that static comparisons keep the ISA and ABI fixed."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock


SOURCE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "compare_cost_models", SOURCE / "compare_cost_models.py"
)
COMPARE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COMPARE)


class TestCompileKernels(unittest.TestCase):
    def test_compile_command_pins_64_bit_abi(self):
        commands = []

        def compile_stub(cmd, **kwargs):
            commands.append(cmd)
            Path(cmd[cmd.index("-o") + 1]).write_text("\tret\n")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kernel = root / "kernel.c"
            kernel.write_text("int kernel(void) { return 0; }\n")
            with mock.patch.object(COMPARE, "OPT_LEVELS", ("-O2",)), mock.patch.object(
                COMPARE.subprocess, "run", side_effect=compile_stub
            ):
                rows = COMPARE.compile_kernels(
                    "riscv-none-elf-gcc", [kernel], root / "out", ["rocket"]
                )

        self.assertTrue(rows[0]["supported"])
        self.assertIn("-march=rv64gc", commands[0])
        self.assertIn("-mabi=lp64d", commands[0])
        self.assertIn("-mtune=rocket", commands[0])


if __name__ == "__main__":
    unittest.main()
