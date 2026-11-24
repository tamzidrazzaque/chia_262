#!/usr/bin/env python3
"""Crossover tables: hardware div/rem vs GCC 15.1 reciprocal sequence on MegaBOOM.

  python3 crossover.py [--measured results/verilator-megaboom-rtl/wave2/results.csv] > crossover.md

[model] hw latency (issue -> dependent issue) = unit L (rtl-model closed form, unit-RTL
validated) + CORE (3, re-fit on the full core: F_offset in analyze.py); seq latency =
dataflow of the GCC body with mul 6 / ALU 1.  With --measured, the measured
[verilator-megaboom-rtl] per-op latencies (op_lat_calib) are put next to the model.
"""
import argparse
import csv
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gen_rd  # noqa: E402
from analyze import seq_model, CORE  # noqa: E402
from boomhw.muldiv_model import closed_form_cycles  # noqa: E402


def hw_stats(t, op, d, lo, hi, n=4000, seed=1):
    R = random.Random(seed)
    fn, dw = gen_rd.FN[(t, op)]
    xs = [R.randrange(lo, hi) for _ in range(n)] + [lo, hi - 1]
    c = [closed_form_cycles(fn, dw, gen_rd.reg(t, x), d) + CORE for x in xs]
    return sum(c) / len(c), max(c), min(c)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--measured", action="append", default=[])
    a = ap.parse_args()
    meas = {}
    for p in a.measured:
        for r in csv.DictReader(open(p)):
            if r["cat"] != "dep":
                continue
            key = (r["type"], r["op"], int(r["d"]), r["impl"], r["range"])
            meas[key] = float(r["op_lat_calib"])
    seqm = {}
    for (t, op, d, impl, rn), v in meas.items():
        if impl == "seq":
            seqm.setdefault((t, op, d), v)
    print("# hw div/rem vs GCC 15.1 sequence, latency per op (issue -> dependent issue), MegaBOOM\n")
    print("Columns: seq = sequence latency; hw mean/worst = hardware latency averaged over / worst case")
    print("over a uniform dividend in the range. [model] = formula; [meas] = [verilator-megaboom-rtl]")
    print("op_lat_calib of the dep kernel (16 dividends drawn from the range). HW<SEQ marks a latency win.\n")
    for t in gen_rd.TYPES:
        for op in ("div", "mod"):
            print(f"\n## {t} {op}\n")
            print("| d | seq [model] | seq [meas] | range | hw mean [model] | hw worst [model] | hw [meas] | latency winner (model mean / meas) |")
            print("|---|---|---|---|---|---|---|---|")
            for d in gen_rd.DIVS:
                L, nu = seq_model(t, op, d)
                sm = seqm.get((t, op, d))
                for rn, (lo, hi) in gen_rd.ranges_for(t, d).items():
                    mean, worst, best = hw_stats(t, op, d, lo, hi)
                    hm = meas.get((t, op, d, "hw", rn))
                    w1 = "HW" if mean < L else ("tie" if mean == L else "SEQ")
                    w2 = "" if hm is None or sm is None else ("HW" if hm < sm - 0.25 else ("tie" if abs(hm - sm) <= 0.25 else "SEQ"))
                    print(f"| {d} | {L} ({nu} uops) | {'' if sm is None else f'{sm:.2f}'} | {rn} [{lo},{hi}) | {mean:.2f} | {worst} | "
                          f"{'' if hm is None else f'{hm:.2f}'} | {w1} / {w2} |")


if __name__ == "__main__":
    main()
