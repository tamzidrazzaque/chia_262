import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "rtl_unit_sim"))
import firrtl_extract as fe  # noqa: E402

FIR = os.path.join(ROOT, "src_snapshot", "firesim-generated", "FireSimMegaBoomV3.fir.gz")

TOY = """FIRRTL version 3.3.0
circuit Top :
  module Leaf :
    input clock : Clock
    input reset : Reset
    output io : UInt<1>
    io <= UInt<1>(0)

  module Mid :
    input clock : Clock
    input reset : Reset
    inst l of Leaf
    l.clock <= clock

  module Other :
    input clock : Clock
"""


class TestFirrtlExtract(unittest.TestCase):
    def test_toy_closure(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "t.fir")
        open(p, "w").write(TOY)
        text, names = fe.extract(p, "Mid")
        self.assertEqual(names, ["Mid", "Leaf"])
        self.assertTrue(text.startswith("FIRRTL version 3.3.0\ncircuit Mid :"))
        self.assertIn("input reset : UInt<1>", text.split("module Leaf")[0])  # top reset concretised
        self.assertNotIn("module Other", text)

    @unittest.skipUnless(os.path.exists(FIR), "elaborated FIRRTL not present")
    def test_real_divsqrt_closure(self):
        _, names = fe.extract(FIR, "DivSqrtRecF64")
        self.assertEqual(len(names), 6)
        self.assertIn("DivSqrtRecF64_mulAddZ31", names)
        text, names = fe.extract(FIR, "MulDiv")
        self.assertEqual(names, ["MulDiv"])
        self.assertIn("node eOutPos", text)  # divEarlyOut elaborated in


if __name__ == "__main__":
    unittest.main()
