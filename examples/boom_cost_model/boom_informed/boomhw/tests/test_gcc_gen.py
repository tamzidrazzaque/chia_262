import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from boomhw import extract as ex, gcc_gen, timing, anish_diff, cli  # noqa: E402
from boomhw import muldiv_model as mdm  # noqa: E402

SRC = os.path.join(ROOT, "src_snapshot")
RISCV_MD = cli.GCC_RISCV_MD
GCC_BUILD = "/home/eecs/trazzaque/spec2017-research/compiler-loop/build/gcc/build/genattrtab"
ANISH_REPO = "/scratch/trazzaque/chia_262"


class TestGcc(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = ex.extract(SRC)
        cls.types = gcc_gen.gcc_types_from_md(open(RISCV_MD).read()) if os.path.exists(RISCV_MD) else None
        cls.md, cls.v = gcc_gen.generate_dfa(cls.m, cls.types)
        cls.resv = anish_diff.parse_md(cls.md)

    def test_parens_balanced(self):
        depth = 0
        for ch in re.sub(r'"[^"]*"', '""', re.sub(r";[^\n]*", "", self.md)):
            depth += ch == "("
            depth -= ch == ")"
            self.assertGreaterEqual(depth, 0)
        self.assertEqual(depth, 0)

    def test_every_gcc_type_has_reservation(self):
        if not self.types:
            self.skipTest("GCC riscv.md not available")
        covered = set()
        for r in self.resv:
            covered.update(r["types"])
        missing = [t for t in self.types if t not in covered and t != "ghost"]
        self.assertEqual(missing, [])

    def test_no_type_reserved_twice(self):
        seen = {}
        for r in self.resv:
            for t in r["types"]:
                key = (t, r["mode"])
                self.assertNotIn(key, seen, f"{t} in {r['name']} and {seen.get(key)}")
                seen[key] = r["name"]

    def test_latencies_follow_model(self):
        by = {r["name"]: r for r in self.resv}
        rows, _ = timing.class_table(self.m)
        t = {r["cls"]: r for r in rows}
        self.assertEqual(by["boom_imul"]["latency"], t["imul"]["latency"])
        self.assertEqual(by["boom_imul"]["latency"], 2 + self.m["core"]["imulLatency"]["value"] + 1)
        self.assertEqual(by["boom_load"]["latency"], 4)
        self.assertEqual(by["boom_fp"]["latency"], 2 + self.m["fpu_params"]["dfmaLatency"]["value"] + 1)
        self.assertEqual(by["boom_idiv_di"]["latency"],
                         timing.div_core_latency(mdm.FN_DIVU, 1, 0xF123_4567_89AB_CDEF, 10))
        self.assertEqual(by["boom_imul"]["resources"], "boom_int2")
        self.assertTrue(by["boom_idiv_di"]["resources"].startswith("boom_int3+boom_idiv,boom_idiv*"))
        occ = int(by["boom_idiv_di"]["resources"].rsplit("*", 1)[1]) + 1
        self.assertEqual(occ, by["boom_idiv_di"]["latency"])
        self.assertEqual(by["boom_branch"]["resources"], "(boom_int0|boom_int1|boom_int2|boom_int3)")
        self.assertEqual(by["boom_jump"]["resources"], "boom_int0")
        self.assertEqual(by["boom_i2f"]["resources"], "boom_int0")
        self.assertEqual(by["boom_fdiv"]["latency"], 23)

    def test_hardfloat_phase_formula_matches_unit_rtl(self):
        d, s = timing.hf_core_cycles(self.m["hardfloat_divsqrt_phases"])
        csvp = os.path.join(ROOT, "rtl_unit_sim", "results", "fdiv_results.csv")
        if not os.path.exists(csvp):
            self.skipTest("no unit RTL results")
        import csv
        rows = list(csv.DictReader(open(csvp)))
        self.assertTrue(all(r["ok"] == "1" for r in rows))
        self.assertEqual({int(r["cycles_fire_to_out"]) for r in rows if r["op"] == "div"}, {d})
        self.assertEqual({int(r["cycles_fire_to_out"]) for r in rows if r["op"] == "sqrt"}, {s})

    def test_tune_table(self):
        sug, c = gcc_gen.tune_suggestion(self.m)
        self.assertIn("static const struct riscv_tune_param boom_tune_info", c)
        self.assertEqual(c.count("/*"), 19)  # header + 18 fields
        self.assertTrue(sug["use_divmod_expansion"]["suggest"])
        self.assertEqual(sug["issue_rate"]["suggest"], 4)

    @unittest.skipUnless(os.path.exists(GCC_BUILD), "GCC 15 generator binaries not present")
    def test_gcc_generators_accept_dfa(self):
        d = tempfile.mkdtemp()
        try:
            mdp = os.path.join(d, "boom.md")
            open(mdp, "w").write(self.md)
            out = subprocess.run([os.path.join(ROOT, "gcc_check", "check_dfa.sh"), mdp, os.path.join(d, "chk")],
                                 capture_output=True, text=True, timeout=600)
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
            auto = open(os.path.join(d, "chk", "tmp-automata.cc")).read()
            for a in ("boom_int", "boom_mem", "boom_fp", "boom_idiv_auto", "boom_fdiv_auto"):
                self.assertIn(f"{a}_transitions", auto)
        finally:
            shutil.rmtree(d)


class TestAnishDiff(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.isdir(ANISH_REPO):
            raise unittest.SkipTest("CHIA repo absent")
        text, commit = anish_diff.load_anish(ANISH_REPO)
        cls.a = anish_diff.evaluate_anish(text)
        cls.m = ex.extract(SRC)

    def test_parse_anish_md(self):
        idx = anish_diff.type_index(anish_diff.parse_md(self.a["md"]))
        self.assertEqual(idx["idiv:DI"]["latency"], 66)
        self.assertEqual(idx["idiv:SI"]["latency"], 34)
        self.assertEqual(idx["imul"]["latency"], 3)
        self.assertEqual(idx["load"]["latency"], 3)
        self.assertEqual(idx["branch"]["resources"], "boom_alu0")
        self.assertEqual(self.a["SEED_COSTS"]["int_div"], [6, 6])

    def test_diff_topics(self):
        d = anish_diff.diff(self.m, self.a)
        topics = {x["topic"] for x in d}
        for t in ("imul scheduling latency", "load-use latency", "divider early-out", "int_div cost (SEED_COSTS)",
                  "branch port", "idiv port / ALU blocking"):
            self.assertIn(t, topics)
        byt = {x["topic"]: x for x in d}
        self.assertEqual(byt["imul scheduling latency"]["rtl_model"], 6)
        self.assertEqual(byt["load-use latency"]["rtl_model"]["int"], 4)


class TestRocketCrosscheck(unittest.TestCase):
    def test_earlyout_explains_rocket_f2(self):
        rows = cli.rocket_crosscheck()
        for r in rows:
            # Rocket pipeline overhead should be a small positive constant with early-out ...
            self.assertGreater(r["residual_earlyout"], 1.0, r)
            self.assertLess(r["residual_earlyout"], 2.0, r)
        res = [r["residual_earlyout"] for r in rows]
        self.assertLess(max(res) - min(res), 0.25, res)  # near-constant overhead
        # ... while a no-early-out divider cannot produce the measured spread
        self.assertTrue(any(r["residual_no_earlyout"] < -3 for r in rows))


if __name__ == "__main__":
    unittest.main()
