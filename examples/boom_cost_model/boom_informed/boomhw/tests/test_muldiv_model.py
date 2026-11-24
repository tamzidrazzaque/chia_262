import csv
import os
import random
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from boomhw import muldiv_model as m  # noqa: E402

RTL_CSV = os.path.join(ROOT, "rtl_unit_sim", "results", "muldiv_results.csv")


class TestAgainstUnitRTL(unittest.TestCase):
    """Verilator run of the MulDiv module cut from the FireSim MegaBOOM FIRRTL."""

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(RTL_CSV):
            raise unittest.SkipTest("run rtl_unit_sim/run_unit_rtl.sh first")
        cls.rows = list(csv.DictReader(open(RTL_CSV)))

    def test_rtl_results_correct(self):
        self.assertGreater(len(self.rows), 10000)
        self.assertTrue(all(r["ok"] == "1" for r in self.rows))
        self.assertTrue(all(r["ready_gap"] == "1" for r in self.rows))

    def test_simulate_matches_rtl_cycles_and_data(self):
        for r in self.rows:
            fn, dw, a, b = int(r["fn"]), int(r["dw"]), int(r["in1"], 16), int(r["in2"], 16)
            data, cyc, _ = m.simulate(fn, dw, a, b)
            self.assertEqual(cyc, int(r["cycles_fire_to_resp"]), r)
            self.assertEqual(data, int(r["data"], 16), r)

    def test_closed_form_matches_rtl(self):
        for r in self.rows:
            fn, dw, a, b = int(r["fn"]), int(r["dw"]), int(r["in1"], 16), int(r["in2"], 16)
            self.assertEqual(m.closed_form_cycles(fn, dw, a, b), int(r["cycles_fire_to_resp"]), r)

    def test_rtl_range(self):
        cyc = [int(r["cycles_fire_to_resp"]) for r in self.rows]
        self.assertEqual(min(cyc), 4)
        self.assertEqual(max(cyc), 68)


class TestModelProperties(unittest.TestCase):
    def test_random_sim_vs_closed_form_vs_reference(self):
        rng = random.Random(1)
        for _ in range(3000):
            fn = rng.choice((4, 5, 6, 7))
            dw = rng.choice((0, 1))
            a = rng.getrandbits(rng.randint(0, 64))
            b = rng.getrandbits(rng.randint(0, 64))
            if rng.random() < 0.3:
                a = (-a) & ((1 << 64) - 1)
            data, cyc, _ = m.simulate(fn, dw, a, b)
            self.assertEqual(data, m.reference(fn, dw, a, b))
            self.assertEqual(cyc, m.closed_form_cycles(fn, dw, a, b))

    def test_known_points(self):
        self.assertEqual(m.closed_form_cycles(5, 1, 1000, 600), 4)        # equal MSB
        self.assertEqual(m.closed_form_cycles(5, 1, 1 << 63, 1), 66)      # d-v = 63: no early out
        self.assertEqual(m.closed_form_cycles(5, 1, 5, 13), 66)           # msb(a)+1 == msb(b)
        self.assertEqual(m.closed_form_cycles(5, 1, 0, 3), 66)            # zero dividend, divisor 3
        self.assertEqual(m.closed_form_cycles(5, 1, 7, 0), 66)            # divide by zero
        self.assertEqual(m.closed_form_cycles(4, 1, (-5) & (2**64 - 1), 13), 68)  # neg in + neg out

    def test_no_earlyout_is_constant(self):
        cfg = m.MulDivParams()
        for a, b in [(1, 1), (1000, 10), (1 << 63, 3)]:
            self.assertEqual(m.simulate(5, 1, a, b, cfg)[1], 66)

    def test_w_ops_use_64bit_datapath(self):
        # same magnitudes -> same cycles for W and 64-bit unsigned forms
        self.assertEqual(m.closed_form_cycles(5, 0, 0xF1234567, 10), m.closed_form_cycles(5, 1, 0xF1234567, 10))


if __name__ == "__main__":
    unittest.main()
