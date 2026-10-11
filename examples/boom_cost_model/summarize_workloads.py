"""Summarize workload tuning and frozen probe model validation."""
import argparse
import json
import math
from pathlib import Path

from hardware_model import load_runs
from run_workloads import CASES, KERNELS, parse_workload_results
from run_timing import TUNES


def summarize(root):
    """Compute case/geometric mean tune ratios and pointer-chain comparisons."""
    runs, metas = load_runs(root, "workloads", KERNELS, parse_workload_results)
    cases = []
    for k, n, p in CASES:
        kernel = KERNELS[k]
        for tune in TUNES:
            rows = [run[kernel, n, p, tune] for run in runs]
            ratios = [r["speedup"] for r in rows]
            parallel_ratios = ([run[kernel, n, 1, tune]["median_cycles"] / r["median_cycles"]
                                for run, r in zip(runs, rows)] if kernel == "pointer_chase" else [1, 1, 1])
            cases.append({"kernel": kernel, "n": n, "parameter": p, "tune": tune,
                          "speedup_geomean": math.prod(ratios) ** (1 / 3),
                          "min_layout_speedup": min(ratios), "max_layout_speedup": max(ratios),
                          "layout_median_cycles": [r["median_cycles"] for r in rows],
                          "speedup_vs_one_chain": math.prod(parallel_ratios) ** (1 / 3)})
    groups = []
    for kernel in KERNELS:
        for tune in TUNES[1:]:
            rows = [r for r in cases if (r["kernel"], r["tune"]) == (kernel, tune)]
            groups.append({"kernel": kernel, "tune": tune,
                           "speedup_geomean": math.prod(r["speedup_geomean"] for r in rows) ** (1 / len(rows)),
                           "cases": len(rows), "wins_all_layouts_over_1pct": sum(r["min_layout_speedup"] > 1.01 for r in rows),
                           "min_case_speedup": min(r["speedup_geomean"] for r in rows),
                           "max_case_speedup": max(r["speedup_geomean"] for r in rows)})
    return {"samples": 405, "groups": groups, "cases": cases,
            "compiler": metas[0]["gcc"],
            "notes": "Medium BOOM; 3 layouts, 3 samples/cell, 2 calls/sample. Equal-weight geometric means, "
                     "not a workload-weighted or SPEC score. >1% is a descriptive threshold, not significance. "
                     "Pointer footprints are 4*n bytes; 1,024 loads per call for every chain count. "
                     "Warm-up traverses all nodes; 64 KiB exceeds the 16 KiB L1 data cache."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, required=True)
    args = parser.parse_args()
    result = summarize(args.runs)
    (args.runs / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    lines = ["# Medium BOOM remaining workload results", "", result["notes"], "",
             "| Kernel | Tune | Geomean speedup vs Rocket | Case range | >1% wins in every layout |",
             "| --- | --- | ---: | --- | ---: |"]
    for r in result["groups"]:
        lines.append(f"| {r['kernel']} | {r['tune']} | {r['speedup_geomean']:.4f}x | "
                     f"{r['min_case_speedup']:.4f}–{r['max_case_speedup']:.4f}x | {r['wins_all_layouts_over_1pct']}/{r['cases']} |")
    lines.extend(["", "## Cases", "",
                  "Parameter: FIR taps, matrix unused (0), pointer chains. Pointer footprint = 4 × N bytes.", "",
                  "| Kernel | N | Parameter | Tune | Speedup | Placement range | Pointer speedup vs one chain |",
                  "| --- | ---: | ---: | --- | ---: | --- | ---: |"])
    for r in result["cases"]:
        parallel = f"{r['speedup_vs_one_chain']:.4f}x" if r["kernel"] == "pointer_chase" else "—"
        lines.append(f"| {r['kernel']} | {r['n']} | {r['parameter']} | {r['tune']} | "
                     f"{r['speedup_geomean']:.4f}x | {r['min_layout_speedup']:.4f}–{r['max_layout_speedup']:.4f}x | {parallel} |")
    (args.runs / "SUMMARY.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:12]))


if __name__ == "__main__":
    main()
