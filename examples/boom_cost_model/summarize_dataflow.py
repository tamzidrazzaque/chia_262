"""Validate and summarize three Medium BOOM dataflow code placements."""
import argparse
import json
import math
from pathlib import Path

from run_dataflow import KERNELS, WIDTHS, parse_dataflow_results
from run_timing import SIZES, TUNES, file_hash


def summarize(root):
    """Reject mismatched inputs or placements; aggregate ratios descriptively."""
    runs, metas = [], []
    for layout in range(3):
        directory = root / f"medium-layout{layout}"
        meta = json.loads((directory / "metadata.json").read_text())
        if (meta.get("experiment") != "dataflow" or meta["suite"]
                or meta["layout"] != layout or meta["opt"] != "O3"
                or "MediumBoomV3Config" not in meta["simulator"]):
            raise ValueError(f"Unexpected dataflow configuration: {directory}")
        if file_hash(directory / "timing.riscv") != meta["binary_sha256"]:
            raise ValueError("Binary differs from the recorded experiment")
        if metas and any(meta[key] != metas[0][key] for key in
                         ("source_sha256", "gcc", "runtime_gcc", "simulator_sha256")):
            raise ValueError("Sources, compilers, or simulator differ across layouts")
        metas.append(meta)
        rows = parse_dataflow_results((directory / "simulation.log").read_text())
        runs.append({(r["n"], r["kernel"], r["streams"], r["tune"]): r for r in rows})
    for kernel in KERNELS:
        slots = None
        for tune in TUNES:
            symbol = f"{kernel}_{tune.replace('-', '_')}"
            addresses = {m["kernel_addresses"][symbol] for m in metas}
            if len(addresses) != 3 or (slots is not None and slots != addresses):
                raise ValueError("Unbalanced code addresses across tunes")
            slots = addresses
    cases = []
    for n in SIZES:
        for kernel in KERNELS:
            for width in (WIDTHS if kernel == "independent_streams" else (1,)):
                for tune in TUNES:
                    rows = [run[n, kernel, width, tune] for run in runs]
                    ratios = [r["speedup"] for r in rows]
                    parallel_ratios = [run[n, kernel, 1, tune]["median_cycles"] / r["median_cycles"]
                                       for run, r in zip(runs, rows)]
                    cases.append({"n": n, "kernel": kernel, "streams": width, "tune": tune,
                                  "speedup_geomean": math.prod(ratios) ** (1 / 3),
                                  "min_layout_speedup": min(ratios),
                                  "max_layout_speedup": max(ratios),
                                  "layout_median_cycles": [r["median_cycles"] for r in rows],
                                  "speedup_vs_one_stream": math.prod(parallel_ratios) ** (1 / 3)})
    groups = []
    for kernel in KERNELS:
        for width in (WIDTHS if kernel == "independent_streams" else (1,)):
            for tune in TUNES[1:]:
                rows = [r for r in cases if (r["kernel"], r["streams"], r["tune"]) == (kernel, width, tune)]
                groups.append({"kernel": kernel, "streams": width, "tune": tune,
                               "speedup_geomean": math.prod(r["speedup_geomean"] for r in rows) ** (1 / 3),
                               "wins_every_layout_over_1pct": sum(r["min_layout_speedup"] > 1.01 for r in rows)})
    return {"groups": groups, "cases": cases, "samples": 486,
            "notes": "Medium BOOM; warm cache; 2 calls/sample, 3 samples/cell, 3 layouts. "
                     "Geometric means weight sizes and placements equally. Placement ranges are not "
                     "confidence intervals. Includes common call/counter overhead; not a SPEC score. "
                     "Stream width changes dependency structure; it is not a compiler unroll factor."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, required=True)
    args = parser.parse_args()
    result = summarize(args.runs)
    (args.runs / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    lines = ["# Medium BOOM dataflow results", "", result["notes"], "",
             "| Kernel | Streams | Tune | Geomean speedup vs Rocket | Sizes >1% faster in every layout |",
             "| --- | ---: | --- | ---: | ---: |"]
    for r in result["groups"]:
        lines.append(f"| {r['kernel']} | {r['streams']} | {r['tune']} | "
                     f"{r['speedup_geomean']:.4f}x | {r['wins_every_layout_over_1pct']}/3 |")
    lines.extend(["", "## Individual cases", "",
                  "| N | Kernel | Streams | Tune | Speedup vs Rocket | Placement range | Speedup vs same tune, one stream |",
                  "| ---: | --- | ---: | --- | ---: | --- | ---: |"])
    for r in result["cases"]:
        lines.append(f"| {r['n']} | {r['kernel']} | {r['streams']} | {r['tune']} | "
                     f"{r['speedup_geomean']:.4f}x | {r['min_layout_speedup']:.4f}–{r['max_layout_speedup']:.4f}x | "
                     f"{r['speedup_vs_one_stream']:.4f}x |")
    (args.runs / "SUMMARY.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:18]))


if __name__ == "__main__":
    main()
