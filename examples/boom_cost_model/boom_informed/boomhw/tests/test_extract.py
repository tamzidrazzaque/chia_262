import os
import re
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from boomhw import extract as ex  # noqa: E402
from boomhw.scala_src import SourceTree, SourceError  # noqa: E402

SRC = os.path.join(ROOT, "src_snapshot")
LOG = os.path.join(SRC, "firesim-generated", "FireSimMegaBoomV3.chisel.log")
DTS = os.path.join(SRC, "firesim-generated", "FireSimMegaBoomV3.dts")


def check_src(test, src, token=None):
    """src is 'generators/<path>:<line>' and the line exists (and contains token)."""
    m = re.fullmatch(r"generators/(.+):(\d+)", src)
    test.assertIsNotNone(m, src)
    path, line = m.group(1), int(m.group(2))
    lines = open(os.path.join(SRC, path)).read().splitlines()
    test.assertLessEqual(line, len(lines), src)
    if token:
        test.assertIn(token, lines[line - 1], src)


class TestExtract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = ex.extract(SRC, LOG, DTS)

    def test_core_params(self):
        c = self.m["core"]
        self.assertEqual(c["fetchWidth"]["value"], 8)
        self.assertEqual(c["decodeWidth"]["value"], 4)
        self.assertEqual(c["numRobEntries"]["value"], 128)
        self.assertEqual(c["numIntPhysRegisters"]["value"], 128)
        self.assertEqual(c["numFpPhysRegisters"]["value"], 128)
        self.assertEqual(c["numLdqEntries"]["value"], 32)
        self.assertEqual(c["numStqEntries"]["value"], 32)
        self.assertEqual(c["numFetchBufferEntries"]["value"], 32)
        self.assertEqual(c["imulLatency"]["value"], 3)
        self.assertEqual(c["imulLatency"]["origin"], "default")
        self.assertEqual(c["ftqEntries"]["value"], 40)
        self.assertFalse(c["useZba"]["value"] or c["useZbb"]["value"] or c["useZbs"]["value"])
        check_src(self, c["fetchWidth"]["src"][0], "fetchWidth = 8")
        check_src(self, c["imulLatency"]["src"][0], "imulLatency")

    def test_issue_queues(self):
        q = self.m["issue_queues"]
        self.assertEqual({k: (v["issueWidth"]["value"], v["numEntries"]["value"], v["dispatchWidth"]["value"])
                          for k, v in q.items()},
                         {"mem": (2, 24, 4), "int": (4, 40, 4), "fp": (2, 32, 4)})
        check_src(self, q["int"]["issueWidth"]["src"][0], "IQT_INT")

    def test_port_map(self):
        ip = {p["port"]: p["fus"] for p in self.m["exec_ports"]["int"]}
        self.assertEqual(ip["int0"], ["ALU", "JMP", "I2F"])
        self.assertEqual(ip["int1"], ["ALU", "CSR"])
        self.assertEqual(ip["int2"], ["ALU", "IMUL"])
        self.assertEqual(ip["int3"], ["ALU", "IDIV"])
        fp = self.m["exec_ports"]["fp"]
        self.assertTrue(any("FDIV" in f for f in fp[0]["fus"]))
        self.assertFalse(any("FDIV" in f for f in fp[1]["fus"]))
        self.assertEqual(len(self.m["exec_ports"]["mem"]), 2)

    def test_muldiv_params(self):
        p = self.m["muldiv_params"]
        self.assertEqual(p["divUnroll"]["value"], 1)
        self.assertTrue(p["divEarlyOut"]["value"])
        self.assertEqual(p["divEarlyOutGranularity"]["value"], 1)
        check_src(self, p["divEarlyOut"]["src"][0], "divEarlyOut=true")
        check_src(self, p["divUnroll"]["src"][0], "divUnroll")

    def test_fpu(self):
        f = self.m["fpu_params"]
        self.assertEqual((f["sfmaLatency"]["value"], f["dfmaLatency"]["value"], f["divSqrt"]["value"]), (4, 4, True))
        self.assertEqual(f["sfmaLatency"]["origin"], "config")  # overrides rocket default 3

    def test_decode_classes(self):
        d = self.m["decode"]
        for op in ("MUL", "MULH", "MULHU", "MULHSU", "MULW"):
            self.assertEqual(d[op]["fu"], "FU_MUL")
            self.assertFalse(d[op]["bypassable"])
        for op in ("DIV", "DIVU", "REM", "REMU", "DIVW", "DIVUW", "REMW", "REMUW"):
            self.assertEqual(d[op]["fu"], "FU_DIV")
        self.assertEqual(d["BEQ"]["fu"], "FU_ALU")
        self.assertEqual(d["AUIPC"]["fu"], "FU_JMP")
        self.assertFalse(d["AUIPC"]["bypassable"])
        self.assertTrue(d["ADD"]["bypassable"])
        self.assertEqual(d["FSD"]["iq"], "IQT_MFP")
        self.assertEqual(d["FCVT_D_L"]["iq"], "IQT_INT")
        check_src(self, d["MULHU"]["src"], "MULHU")

    def test_caches(self):
        c = self.m["caches"]
        self.assertEqual(c["dcache"]["sizeBytes"]["value"], 32768)
        self.assertEqual(c["icache"]["sizeBytes"]["value"], 32768)
        self.assertEqual(c["dcache"]["nMSHRs"]["value"], 8)
        self.assertEqual(self.m["dts"]["d_cache_size"], 32768)
        self.assertEqual(self.m["dts"]["l2_cache_size"], 524288)
        self.assertNotIn("zb", self.m["dts"]["isa"])

    def test_anchors_resolve(self):
        for k, a in self.m["anchors"].items():
            check_src(self, a["src"])

    def test_elaboration_crosscheck(self):
        self.assertTrue(self.m["elaboration_crosscheck"]["all_match"],
                        [c for c in self.m["elaboration_crosscheck"]["checks"] if not c["match"]])

    def test_anchor_fails_loudly(self):
        st = SourceTree(SRC)
        with self.assertRaises(SourceError):
            st.anchor(ex.P["core"], r"this pattern does not exist anywhere 12345")


class TestScalaHelpers(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.d, "x"))
        with open(os.path.join(self.d, "x", "A.scala"), "w") as f:
            f.write("case class P(\n  a: Int = 1, // c\n  /* block */ b: Boolean = true,\n"
                    "  c: Seq[Int] = Seq(1, 2),\n  d: Option[Q] = Some(Q(x=3))\n)\n"
                    "class C extends Config(new Z(k = 4*4, m = IQT_INT.litValue, n = f(1, 2)))\n")
        self.st = SourceTree(self.d)

    def test_case_class_defaults(self):
        d = self.st.case_class_defaults("x/A.scala", "P")
        self.assertEqual(d["a"]["value"], 1)
        self.assertEqual(d["b"]["value"], True)
        self.assertEqual(d["c"]["expr"], "Seq(1, 2)")
        self.assertEqual(d["d"]["expr"], "Some(Q(x=3))")
        self.assertEqual(d["b"]["src"], "generators/x/A.scala:3")

    def test_named_args(self):
        o, c = self.st.block("x/A.scala", r"new Z\(")
        args = self.st.named_call_args("x/A.scala", o, c)
        self.assertEqual(args["k"]["value"], 16)
        self.assertEqual(args["m"]["value"], "IQT_INT")
        self.assertEqual(args["n"]["expr"], "f(1, 2)")


if __name__ == "__main__":
    unittest.main()
