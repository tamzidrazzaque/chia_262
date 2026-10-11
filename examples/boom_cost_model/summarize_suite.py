"""Combine complete Small/Medium BOOM suites across three code placements."""
import argparse
import json
import math
from pathlib import Path

from run_timing import KERNELS, PATTERNS, SIZES, TUNES, parse_suite_results


def summarize(root):
    """Require matching experiment inputs and balanced addresses before grouping."""
    cases = []
    source_hashes = None
    compiler = None
    runtime_compiler = None
    for core in ("small", "medium"):
        runs = []
        metas = []
        for layout in range(3):
            directory = root / f"{core}-layout{layout}"
            meta = json.loads((directory / "metadata.json").read_text())
            if not meta["suite"] or meta["layout"] != layout or meta["opt"] != "O3":
                raise ValueError(f"Unexpected experiment configuration: {directory}")
            if source_hashes is None:
                source_hashes, compiler = meta["source_sha256"], meta["gcc"]
                runtime_compiler = meta["runtime_gcc"]
            if (meta["source_sha256"] != source_hashes or meta["gcc"] != compiler
                    or meta["runtime_gcc"] != runtime_compiler):
                raise ValueError("Suite inputs or experimental compiler differ between runs")
            expected_name = f"{core.capitalize()}BoomV3Config"
            if expected_name not in meta["simulator"]:
                raise ValueError(f"Unexpected simulator for {core}")
            metas.append(meta)
            # Parse raw logs again; stale summary files cannot count as a run.
            rows = parse_suite_results((directory / "simulation.log").read_text())
            runs.append({(r["n"], r["pattern"], r["kernel"], r["tune"]): r for r in rows})
        if len({m["simulator_sha256"] for m in metas}) != 1:
            raise ValueError("Simulator changed within a core's layout comparison")
        for kernel in KERNELS:
            slots = None
            for tune in TUNES:
                symbol = f"{kernel}_{tune.replace('-', '_')}"
                positions = {m["kernel_addresses"][symbol] for m in metas}
                if len(positions) != 3 or (slots is not None and positions != slots):
                    raise ValueError("Code addresses are not balanced across tunes")
                slots = positions
        for n in SIZES:
            for pattern in PATTERNS:
                for kernel in KERNELS:
                    for tune in TUNES[1:]:
                        rows = [run[n, pattern, kernel, tune] for run in runs]
                        ratios = [row["speedup"] for row in rows]
                        cases.append({"core": core, "n": n, "pattern": pattern,
                                      "kernel": kernel, "tune": tune,
                                      "speedup_geomean": math.prod(ratios) ** (1 / 3),
                                      "min_layout_speedup": min(ratios),
                                      "max_layout_speedup": max(ratios),
                                      "layout_speedups": ratios})
    groups = []
    for core in ("small", "medium"):
        for kernel in KERNELS:
            for tune in TUNES[1:]:
                rows = [r for r in cases if (r["core"], r["kernel"], r["tune"]) == (core, kernel, tune)]
                groups.append({"core": core, "kernel": kernel, "tune": tune,
                               "cases": len(rows),
                               "speedup_geomean": math.prod(r["speedup_geomean"] for r in rows) ** (1 / len(rows)),
                               "min_case_speedup": min(r["speedup_geomean"] for r in rows),
                               "max_case_speedup": max(r["speedup_geomean"] for r in rows),
                               "wins_all_layouts_over_1pct": sum(r["min_layout_speedup"] > 1.01 for r in rows),
                               "losses_all_layouts_over_1pct": sum(r["max_layout_speedup"] < 0.99 for r in rows)})
    return {"compiler": compiler, "runtime_compiler": runtime_compiler,
            "groups": groups, "cases": cases,
            "notes": "Equal weight to each size/pattern and layout; this is not a workload-weighted or SPEC score. Three samples per cell, two calls per sample. The 1% threshold is descriptive, not a statistical significance test."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, required=True)
    args = parser.parse_args()
    result = summarize(args.runs)
    (args.runs / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    lines = ["# BOOM tuning sensitivity results", "", result["notes"], "",
             "| Core | Kernel | Tune | Geomean speedup | Case range | >1% wins in every layout |",
             "| --- | --- | --- | ---: | --- | ---: |"]
    for r in result["groups"]:
        lines.append(f"| {r['core']} | {r['kernel']} | {r['tune']} | {r['speedup_geomean']:.4f}x | "
                     f"{r['min_case_speedup']:.4f}–{r['max_case_speedup']:.4f}x | {r['wins_all_layouts_over_1pct']}/12 |")
    lines.extend(["", "## Individual cases", "",
                  "| Core | Size | Pattern | Kernel | Tune | Geomean speedup | Range across layouts |",
                  "| --- | ---: | --- | --- | --- | ---: | --- |"])
    for r in result["cases"]:
        lines.append(f"| {r['core']} | {r['n']} | {r['pattern']} | {r['kernel']} | {r['tune']} | "
                     f"{r['speedup_geomean']:.4f}x | {r['min_layout_speedup']:.4f}–{r['max_layout_speedup']:.4f}x |")
    (args.runs / "SUMMARY.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:23]))


if __name__ == "__main__":
    main()
