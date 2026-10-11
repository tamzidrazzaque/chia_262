"""Fit effective BOOM operation costs from probes and evaluate held-out loops.

This prototype predicts cycles outside GCC. It does not install a backend tune.
Fitting reads only probe measurements; validation reads FIR/matrix timings only
after the model JSON has been written. No held-out parameters are fitted.
"""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import statistics

from run_probes import KERNELS as PROBE_KERNELS, parse_probe_results
from run_workloads import KERNELS as WORKLOAD_KERNELS, parse_workload_results
from run_timing import TUNES, file_hash


def load_runs(root, profile, kernels, parse):
    """Revalidate raw logs, fingerprints, sources, and balanced code addresses."""
    runs, metas = [], []
    for layout in range(3):
        directory = root / f"medium-layout{layout}"
        meta = json.loads((directory / "metadata.json").read_text())
        if (meta.get("experiment") != profile or meta["suite"]
                or meta["layout"] != layout or meta["opt"] != "O3"
                or "MediumBoomV3Config" not in meta["simulator"]):
            raise ValueError(f"Unexpected experiment configuration: {directory}")
        if file_hash(directory / "timing.riscv") != meta["binary_sha256"]:
            raise ValueError("Binary differs from recorded experiment")
        if file_hash(Path(meta["simulator"])) != meta["simulator_sha256"]:
            raise ValueError("Simulator differs from recorded experiment")
        for name, digest in meta["source_sha256"].items():
            if file_hash(root / "sources" / name) != digest:
                raise ValueError("Archived source differs from recorded experiment")
        if metas and any(meta[key] != metas[0][key] for key in
                         ("source_sha256", "gcc", "runtime_gcc", "simulator_sha256")):
            raise ValueError("Experiment inputs differ across layouts")
        rows = parse((directory / "simulation.log").read_text())
        runs.append({(r["kernel"], r["n"], r["streams"], r["tune"]): r for r in rows})
        metas.append(meta)
    for kernel in kernels:
        slots = None
        for tune in TUNES:
            symbol = f"{kernel}_{tune.replace('-', '_')}"
            positions = {m["kernel_addresses"][symbol] for m in metas}
            if len(positions) != 3 or (slots is not None and positions != slots):
                raise ValueError("Unbalanced code addresses across tunes")
            slots = positions
    return runs, metas


def fit_model(runs):
    """Use length differences to remove fixed overhead; median over 9 slopes.

    Width-one slopes estimate effective chain cost. Width-eight slopes estimate
    sustained cost with eight independent chains, not guaranteed peak hardware
    throughput. Both include the small repeated-block loop contribution.
    """
    operations, intercepts = {}, []
    for kernel in PROBE_KERNELS:
        estimates = {}
        for width in (1, 8):
            slopes = []
            for run in runs:
                for tune in TUNES:
                    short = run[kernel, 128, width, tune]["median_cycles"]
                    long = run[kernel, 512, width, tune]["median_cycles"]
                    slope = (long - short) / (2 * (512 - 128))
                    if not math.isfinite(slope) or slope <= 0:
                        raise ValueError("Probe lengths do not yield a positive slope")
                    slopes.append(slope)
                    intercepts.append(short - 2 * 128 * slope)
            estimates[str(width)] = {"cycles_per_operation": statistics.median(slopes),
                                     "min": min(slopes), "max": max(slopes)}
        operations[kernel.removeprefix("probe_")] = estimates
    choices = {}
    for width in (1, 2, 4, 8):
        costs = {op: max(operations[op]["1"]["cycles_per_operation"] / width,
                         operations[op]["8"]["cycles_per_operation"])
                 for op in ("mul", "shift")}
        choices[str(width)] = {"preferred": min(costs, key=costs.get), "predicted_cycles_per_op": costs}
    return {"schema": 1, "target": "MediumBoomV3Config", "isa": "rv64gc", "abi": "lp64d",
            "operations": operations, "mul13_choices": choices,
            "fixed_overhead_cycles": max(0, min(intercepts)),
            "method": "Median length-difference slopes; max of dependency and resource bounds. "
                      "Effective block costs include loop contribution. Only probe timings fit parameters.",
            "limitations": "Eight chains may not saturate every unit. The resource-bound predictor omits "
                           "cache misses, branch mispredictions, detailed scheduling, and register pressure. "
                           "Scalar optimization costs are not literal scheduler latencies. No GCC integration."}


def extract_loops(text):
    """Extract the innermost multiply loop and enclosing backward loop spans."""
    instructions = []
    for line in text.splitlines():
        match = re.match(r"\s*([0-9a-f]+):\s+[0-9a-f]+\s+([a-z0-9.]+)\s*(.*)$", line)
        if match:
            instructions.append({"address": int(match[1], 16), "op": match[2], "args": match[3]})
    positions = {r["address"]: i for i, r in enumerate(instructions)}
    spans = []
    for end, row in enumerate(instructions):
        if not (row["op"].startswith("b") or row["op"] == "j"):
            continue
        target = re.search(r"(?:,|^|\s)([0-9a-f]+)\s+<", row["args"])
        if not target:
            continue
        start = positions.get(int(target[1], 16))
        if start is not None and start < end:
            body = instructions[start:end + 1]
            if any(r["op"] in ("mul", "mulw") for r in body):
                spans.append((start, end))
    if not spans:
        raise ValueError("No backward multiply loop found")
    inner = min(spans, key=lambda p: p[1] - p[0])
    nested = sorted({p for p in spans if p[0] <= inner[0] and p[1] >= inner[1]},
                    key=lambda p: p[1] - p[0])
    body = instructions[inner[0]:inner[1] + 1]
    return {"instructions_per_inner": len(body),
            "loads_per_inner": sum(r["op"] in ("lw", "lwu", "ld", "lh", "lhu", "lb", "lbu") for r in body),
            "multiplies_per_inner": sum(r["op"] in ("mul", "mulw") for r in body),
            "inner_ops": [r["op"] for r in body],
            "loop_span_lengths": [end - start + 1 for start, end in nested],
            "function_instructions": len(instructions),
            "inner_start": hex(instructions[inner[0]]["address"])}


def predict_cycles(model, features, kernel, n, parameter):
    """Resource-bound estimate for FIR or i/j/k matrix multiplication.

    Count enclosing-loop overhead from linked assembly and known trip counts.
    The accumulation chain uses measured add cost; independent multiplications
    use sustained cost. Load throughput uses the small cached pointer probe.
    """
    if kernel not in ("fir", "matmul"):
        raise ValueError("Only FIR/matmul are held-out model workloads")
    work = n * parameter if kernel == "fir" else n ** 3
    outputs = n if kernel == "fir" else n * n
    spans = features["loop_span_lengths"]
    required = 2 if kernel == "fir" else 3
    if len(spans) != required:
        raise ValueError("Unexpected loop nesting; refusing an unsupported prediction")
    instructions = features["instructions_per_inner"] * work
    instructions += (spans[1] - spans[0]) * outputs
    if kernel == "matmul":
        instructions += (spans[2] - spans[1]) * n
    instructions += features["function_instructions"] - spans[-1]
    ops = model["operations"]
    bounds = {"issue": instructions * ops["add"]["8"]["cycles_per_operation"],
              "multiply": work * features["multiplies_per_inner"] * ops["mul"]["8"]["cycles_per_operation"],
              "memory": (work * features["loads_per_inner"] + outputs) * ops["load"]["8"]["cycles_per_operation"],
              "accumulation": work * ops["add"]["1"]["cycles_per_operation"]}
    return {"predicted_cycles": 2 * max(bounds.values()) + model["fixed_overhead_cycles"],
            "work": work, "dynamic_instruction_estimate": instructions,
            "bounds_per_call": bounds, "dominant_bound": max(bounds, key=bounds.get)}


def evaluate(model, runs, root):
    """Evaluate frozen predictions without updating any fitted parameter."""
    rows = []
    for key in runs[0]:
        kernel, n, parameter, tune = key
        if kernel == "pointer_chase":
            continue
        predictions, measured = [], []
        for layout, run in enumerate(runs):
            asm = root / f"medium-layout{layout}" / f"{kernel}.{tune}.linked.asm"
            prediction = predict_cycles(model, extract_loops(asm.read_text()), kernel, n, parameter)
            predictions.append(prediction["predicted_cycles"])
            measured.append(run[key]["median_cycles"])
        mean_predicted = statistics.mean(predictions)
        mean_measured = statistics.mean(measured)
        rows.append({"kernel": kernel, "n": n, "parameter": parameter, "tune": tune,
                     "predicted_cycles": mean_predicted, "measured_cycles": mean_measured,
                     "signed_error_percent": 100 * (mean_predicted / mean_measured - 1),
                     "layout_predicted_cycles": predictions, "layout_measured_cycles": measured})
    return {"cases": rows, "mean_absolute_percentage_error": statistics.mean(abs(r["signed_error_percent"]) for r in rows),
            "notes": "Held-out timings were not used to fit or retune this model. Errors average layout medians. "
                     "The model predicts costs; this evaluation does not demonstrate a compiler speedup."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("fit", "validate"))
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "fit":
        if args.model.exists():
            parser.error("Model already exists; choose a new output to preserve the frozen model")
        runs, metas = load_runs(args.runs, "probes", PROBE_KERNELS, parse_probe_results)
        model = fit_model(runs)
        model["frozen_at_utc"] = datetime.now(timezone.utc).isoformat()
        model["implementation_sha256"] = file_hash(Path(__file__))
        model["training_fingerprints"] = [{"metadata_sha256": file_hash(args.runs / f"medium-layout{i}" / "metadata.json"),
                                            "log_sha256": file_hash(args.runs / f"medium-layout{i}" / "simulation.log")}
                                           for i in range(3)]
        model["gcc"] = metas[0]["gcc"]
        model["runtime_gcc"] = metas[0]["runtime_gcc"]
        model["simulator_sha256"] = metas[0]["simulator_sha256"]
        args.model.parent.mkdir(parents=True, exist_ok=True)
        args.model.write_text(json.dumps(model, indent=2) + "\n")
        print(json.dumps(model["operations"], indent=2))
    else:
        model = json.loads(args.model.read_text())
        if model["implementation_sha256"] != file_hash(Path(__file__)):
            raise ValueError("Prediction implementation changed after model freeze")
        runs, metas = load_runs(args.runs, "workloads", WORKLOAD_KERNELS, parse_workload_results)
        if any(model[key] != metas[0][key] for key in ("gcc", "runtime_gcc", "simulator_sha256")):
            raise ValueError("Held-out run uses different compilers or simulator")
        result = evaluate(model, runs, args.runs)
        result["model_sha256"] = file_hash(args.model)
        result["frozen_at_utc"] = model["frozen_at_utc"]
        (args.runs / "validation.json").write_text(json.dumps(result, indent=2) + "\n")
        lines = ["# Held-out hardware model validation", "", result["notes"], "",
                 f"Mean absolute percentage error: {result['mean_absolute_percentage_error']:.1f}%", "",
                 "| Kernel | N | Parameter | Tune | Predicted cycles | Measured cycles | Error |",
                 "| --- | ---: | ---: | --- | ---: | ---: | ---: |"]
        for r in result["cases"]:
            lines.append(f"| {r['kernel']} | {r['n']} | {r['parameter']} | {r['tune']} | "
                         f"{r['predicted_cycles']:.1f} | {r['measured_cycles']:.1f} | {r['signed_error_percent']:+.1f}% |")
        (args.runs / "VALIDATION.md").write_text("\n".join(lines) + "\n")
        print("\n".join(lines[:6]))


if __name__ == "__main__":
    main()
