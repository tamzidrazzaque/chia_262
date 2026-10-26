"""Verify instruction parsing and the distinction between opcode mix and order."""

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock


SOURCE = Path(__file__).resolve().parents[1] / "spec_asm_compare.py"
SPEC = importlib.util.spec_from_file_location("spec_asm_compare", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class TestAssemblySummary(unittest.TestCase):
    def test_local_labels_stay_with_their_function(self):
        names = "foo T 0 8\nbar T 8 4\ndata D 0 4\n"
        assembly = ("Disassembly of section .text:\n00000000 <foo>:\n"
                    "   0: addi a0,a0,1\n00000004 <.L1>:\n   4: bne a0,a1,0\n"
                    "00000008 <bar>:\n   8: ret\n")
        result = MODULE.parse_functions(names, assembly)
        self.assertEqual(result["foo"], {"bytes": 8, "opcodes": ["addi", "bne"]})
        self.assertEqual(result["bar"]["opcodes"], ["ret"])

    def test_comparison_separates_selection_from_reordering(self):
        base = {"x.o": {"foo": {"bytes": 8, "opcodes": ["addw", "mulw"]}}}
        order = {"x.o": {"foo": {"bytes": 8, "opcodes": ["mulw", "addw"]}}}
        mix = {"x.o": {"foo": {"bytes": 8, "opcodes": ["slliw", "addw"]}}}
        self.assertEqual(MODULE.compare(base, order)[0]["opcode_change"], "opcode order changed")
        self.assertEqual(MODULE.compare(base, mix)[0]["removed_opcodes"], {"mulw": 1})
        self.assertEqual(MODULE.compare(base, mix)[0]["added_opcodes"], {"slliw": 1})

    def test_collect_includes_nested_library_objects(self):
        with tempfile.TemporaryDirectory() as directory:
            nested = Path(directory) / "lib" / "lzma"
            nested.mkdir(parents=True)
            (nested / "coder.o").touch()
            with mock.patch.object(MODULE.subprocess, "check_output", side_effect=[
                "encode T 0 4\n", "Disassembly of section .text:\n0000 <encode>:\n 0: ret\n"
            ]):
                objects = MODULE.collect(Path(directory), Path("/nm"), Path("/objdump"))
        self.assertEqual(objects["lib/lzma/coder.o"]["encode"]["opcodes"], ["ret"])


if __name__ == "__main__":
    unittest.main()
