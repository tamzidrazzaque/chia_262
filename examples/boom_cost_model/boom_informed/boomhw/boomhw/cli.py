"""python3 -m boomhw.cli [--src DIR] [--from-docker IMAGE] [--anish-repo REPO] [--out DIR]

Builds the MegaBOOM V3 hardware model from Scala sources and emits:
  megaboom_hw_model.json   facts with file:line provenance + timing tables
  boom.md                  generated GCC DFA (drop-in for boom_model.scheduling_description)
  boom_tune_info.c         suggested riscv_tune_param table
  tune_suggestion.json     per-field rationale, RTL value, Anish seed
  latency_throughput.csv   per-class predictions (for the microbenchmark stream)
  div_latency.csv          operand-dependent integer divide predictions
  diff_vs_anish.json/.txt  disagreements with CHIA origin/main boom_model.py
"""
import argparse
import csv
import datetime
import json
import os
import sys

from . import extract as ex
from . import timing
from . import gcc_gen
from . import anish_diff
from . import muldiv_model as mdm
from .scala_src import snapshot_from_docker

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SRC = os.path.join(HERE, "src_snapshot")
GCC_RISCV_MD = "/home/eecs/trazzaque/spec2017-research/compiler-loop/source/gcc/config/riscv/riscv.md"
SNAP_PATHS = ["boom/src/main/scala/v3", "rocket-chip/src/main/scala/rocket", "rocket-chip/src/main/scala/tile",
              "rocket-chip/src/main/scala/subsystem", "chipyard/src/main/scala/config",
              "hardfloat/hardfloat/src/main/scala", "firechip/chip/src/main/scala"]

# Rocket+Saturn F2 measurements (NOT BOOM), from
# /scratch/trazzaque/SLICE/cost-model-out/boom-informed/campaign/FPGA_DIV_MEASUREMENTS.md
# Last field = total timed cycles for N=128 ops (table "Cycles" column, rep 2).
# The table's per_op column is floor(cycles/128); using it truncated the
# measurement by up to 0.58 cycles/op (review.md), so cycles/128 is used here.
ROCKET_F2 = {"dep_divu3": (5, 1, 3, 7449), "dep_divu13": (5, 1, 13, 8006), "dep_divu100": (5, 1, 100, 7882),
             "dep_divu4000": (5, 1, 4000, 7391), "dep_div_neg13": (4, 1, (-13) & timing.M64, 8255)}


def rocket_crosscheck():
    """Replay div_probe.c chains (x0=0x123456789abcdef, 128 dependent divides,
    value collapses to 0) through the MulDiv model and compare with the
    Rocket F2 cycles/op.  Rocket shares rocket-chip MulDiv; its MulDivParams
    in the Saturn image are not known here, so both early-out settings are shown."""
    out = []
    for name, (fn, dw, d, cyc) in ROCKET_F2.items():
        meas = cyc / 128
        row = {"kernel": name, "rocket_f2_cycles": cyc, "rocket_f2_cycles_per_op": round(meas, 2),
               "source_of_measurement": "Rocket+Saturn F2 (not BOOM)"}
        for label, cfg in (("earlyout", mdm.MulDivParams(divEarlyOut=True)), ("no_earlyout", mdm.MulDivParams())):
            x, tot = 0x123456789ABCDEF, 0
            for _ in range(128):
                x, c, _ = mdm.simulate(fn, dw, x, d, cfg)
                tot += c
            row[f"muldiv_model_avg_{label}"] = round(tot / 128, 2)
            row[f"residual_{label}"] = round(meas - tot / 128, 2)
        out.append(row)
    return out


def boom_probe_predictions(model):
    """Predicted MegaBOOM cycles/op for the kernels of campaign/div_probe.c
    (same operands; x0 = 0x123456789abcdef, N = 128).  Derived predictions for
    the microbenchmark stream to validate; loop overhead assumed hidden by OoO."""
    rows, _ = timing.class_table(model)
    t = {r["cls"]: r for r in rows}
    imul, alu = t["imul"]["latency"], 1
    out = []
    for name, (fn, dw, d, _) in ROCKET_F2.items():
        x, lat = 0x123456789ABCDEF, []
        for _ in range(128):
            lat.append(timing.div_core_latency(fn, dw, x, d))
            x = mdm.reference(fn, dw, x, d)
        out.append({"kernel": name, "pred_cycles_per_op": round(sum(lat) / 128, 2),
                    "steady_state_after_collapse": lat[-1], "basis": "unit-RTL MulDiv + derived core offsets"})
    x, lat = 0x123456789ABCDEF, []
    for _ in range(32):   # indep4: 4 chains of 32, one divider -> serialized by occupancy
        lat.append(timing.div_core_interval(5, 1, x, 13))
        x = x // 13
    out += [
        {"kernel": "indep4_divu13", "pred_cycles_per_op": round(sum(lat) / 32, 2),
         "basis": "one MulDiv: independent divides serialize at the issue interval"},
        {"kernel": "dep_mulhu", "pred_cycles_per_op": imul, "basis": "derived"},
        {"kernel": "dep_mulhu13_srli", "pred_cycles_per_op": imul + alu, "basis": "derived"},
        {"kernel": "dep_mulh4000_seq", "pred_cycles_per_op": imul + 2 * alu,
         "basis": "derived (mulh -> srai -> sub on the critical path; sign srai is off-path)"},
        {"kernel": "indep4_mulhu", "pred_cycles_per_op": imul / 4, "basis": "derived (4 chains x 6 cycles, 1 mul/cycle)"},
        {"kernel": "dep_add", "pred_cycles_per_op": 1, "basis": "derived (front-end limits not modelled)"},
    ]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=DEFAULT_SRC)
    ap.add_argument("--from-docker", default=None, help="snapshot sources from this image first")
    ap.add_argument("--anish-repo", default="/scratch/trazzaque/chia_262")
    ap.add_argument("--anish-ref", default="origin/main")
    ap.add_argument("--gcc-riscv-md", default=GCC_RISCV_MD)
    ap.add_argument("--elab-log", default=None)
    ap.add_argument("--dts", default=None)
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    ap.add_argument("--idiv-policy", default="full_width_div10", choices=["full_width_div10", "worst"])
    a = ap.parse_args(argv)
    if a.from_docker:
        snapshot_from_docker(a.from_docker, a.src, SNAP_PATHS)
    elab = a.elab_log or os.path.join(a.src, "firesim-generated", "FireSimMegaBoomV3.chisel.log")
    dts = a.dts or os.path.join(a.src, "firesim-generated", "FireSimMegaBoomV3.dts")
    model = ex.extract(a.src, elab if os.path.exists(elab) else None, dts if os.path.exists(dts) else None)
    rows, hf = timing.class_table(model)
    model["timing"] = {"definitions": timing.__doc__, "classes": rows, "hardfloat_core": hf,
                       "integer_divide_cases": timing.div_table(),
                       "integer_divide_formula": mdm.closed_form_cycles.__doc__}
    model["rocket_f2_crosscheck"] = rocket_crosscheck()
    model["boom_div_probe_predictions"] = boom_probe_predictions(model)
    model["generated"] = datetime.datetime.now().isoformat(timespec="seconds")
    commits = os.path.join(a.src, "SNAPSHOT_COMMITS.txt")
    if os.path.exists(commits):
        model["source_commits"] = dict(l.split() for l in open(commits) if len(l.split()) == 2)
    model["source_image"] = "anishs-chia-f2-driver-cache:19a07f6 (/home/ray/chipyard)"
    gcc_types = None
    if os.path.exists(a.gcc_riscv_md):
        gcc_types = gcc_gen.gcc_types_from_md(open(a.gcc_riscv_md).read())
    md, v = gcc_gen.generate_dfa(model, gcc_types, idiv_policy=a.idiv_policy)
    anish = None
    try:
        text, commit = anish_diff.load_anish(a.anish_repo, a.anish_ref)
        anish = anish_diff.evaluate_anish(text)
        anish["commit"] = commit
    except Exception as e:  # repo missing etc.
        print("warning: could not load Anish model:", e, file=sys.stderr)
    sug, ctab = gcc_gen.tune_suggestion(model, anish["SEED_COSTS"] if anish else None)
    os.makedirs(a.out, exist_ok=True)
    w = lambda name, s: open(os.path.join(a.out, name), "w").write(s)
    w("megaboom_hw_model.json", json.dumps(model, indent=1, default=str))
    w("boom.md", md)
    w("boom_tune_info.c", ctab)
    w("tune_suggestion.json", json.dumps(sug, indent=1, default=str))
    with open(os.path.join(a.out, "latency_throughput.csv"), "w", newline="") as f:
        cw = csv.writer(f)
        cw.writerow(["class", "insns", "gcc_types", "ports", "latency", "recip_thpt", "basis", "note", "src"])
        for r in rows:
            rt = r["recip_thpt"]
            cw.writerow([r["cls"], r["insns"], r["gcc_types"], "+".join(r["ports"]), r["latency"],
                         round(rt, 3) if isinstance(rt, float) else rt, r["basis"], r.get("note", ""),
                         " ".join(r["src"])])
    with open(os.path.join(a.out, "div_latency.csv"), "w", newline="") as f:
        cw = csv.writer(f)
        dt = model["timing"]["integer_divide_cases"]
        cw.writerow(list(dt[0].keys()))
        for r in dt:
            cw.writerow(list(r.values()))
    if anish:
        d = anish_diff.diff(model, anish, gcc_types)
        w("diff_vs_anish.json", json.dumps({"anish_commit": anish["commit"], "anish_seed_costs": anish["SEED_COSTS"],
                                             "anish_md": anish["md"], "disagreements": d}, indent=1, default=str))
        lines = [f"Diff: RTL-derived model vs CHIA {a.anish_ref}:chia/chipyard/boom_model.py ({anish['commit'][:10]})", ""]
        for i, x in enumerate(d, 1):
            lines += [f"{i}. {x['topic']}", f"   anish: {x['anish']}", f"   rtl  : {x['rtl_model']}",
                      f"   verdict: {x['verdict']}", f"   impact: {x['compiler_impact']}",
                      f"   evidence: {', '.join(x['evidence'])}", ""]
        w("diff_vs_anish.txt", "\n".join(lines))
    print(f"wrote outputs to {a.out}; elaboration crosscheck all_match="
          f"{model.get('elaboration_crosscheck', {}).get('all_match')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
