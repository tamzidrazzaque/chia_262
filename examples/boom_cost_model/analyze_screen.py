"""Export hardware observations, surrogate checks and train-only SPEC transfer."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics

from chia.chipyard.cost_model import BASE_COSTS, BASELINE_GCC_SHA256
from chia.chipyard.tuning_search import validation_report
from chia.chipyard.assembly_features import extract


def rank_agreement(pairs):
    good = total = tied_proxy = 0
    for i, (x, y) in enumerate(pairs):
        for px, py in pairs[:i]:
            if abs(x - px) < 1e-5:
                tied_proxy += 1
                continue
            if abs(y - py) < 1e-5:
                continue
            total += 1
            good += (x - px) * (y - py) > 0
    return {"comparable_pairs": total, "tied_proxy_pairs": tied_proxy,
            "pair_rank_accuracy": good / total if total else None}


def analyze(screen: Path, prior: list[Path]):
    result = json.loads((screen / "result.json").read_text())
    if not result["success"] or not result["reports"]:
        raise ValueError("hardware batch did not finish correctly")
    batch = Path(result["batch"])
    build = json.loads((batch / "build.json").read_text())
    binary_hashes = {}
    for line in (batch / "diagnostics/binaries.sha256").read_text().splitlines():
        value, name = line.split(maxsplit=1)
        binary_hashes[Path(name).name] = value
    hardware = json.loads((screen / "hardware.json").read_text())
    target = hashlib.sha256((screen / "hardware.json").read_bytes() +
                            (screen / "config_runtime.yaml").read_bytes() +
                            json.dumps({k: build[k] for k in ("recipe", "flags", "source_sha256")},
                                       sort_keys=True).encode()).hexdigest()
    observations, by_id = [], {}
    for name, compiler in build["variants"].items():
        # Every physical worker contributes a paired ratio against its baseline.
        logs = []
        for data in result["reports"].values():
            if not data["variants"][name]["success"] or not data["variants"][name]["FPGA_executed"]:
                raise ValueError("incorrect or nonhardware label")
            logs.append(math.log(data["screening_speedups"][name]))
        score = math.exp(statistics.mean(logs))
        p = {"costs": compiler.get("costs", BASE_COSTS), "tuning": compiler.get("tuning", "rocket"),
             "scheduling": compiler.get("scheduling", {"issue_rate": 4 if compiler.get("tuning") == "boom" else 1})}
        observation = {"compiler_id": compiler["compiler_id"], "proposal": p, "speedup": score,
                       "correct": True, "FPGA_executed": True, "target_id": target,
                       "executable_sha256": binary_hashes[name],
                       "assembly_features": extract((batch / "diagnostics" / (name + ".s")).read_text())}
        observations.append(observation)
        by_id[compiler["compiler_id"]] = score
    # Identical binaries can differ slightly by batch position/cache state.
    # Treat them as tied proxies rather than crediting those variations as signal.
    code_groups = {}
    for o in observations:
        code_groups.setdefault(o["executable_sha256"], []).append(math.log(o["speedup"]))
    by_id = {o["compiler_id"]: math.exp(statistics.mean(code_groups[o["executable_sha256"]])) for o in observations}
    transfer = []
    for run in prior:
        # Deliberately read only train data; do not read result.json or ref paths.
        old_hardware = json.loads((run / "hardware.json").read_text())
        old_baseline = json.loads((run / "baseline-identity.json").read_text())
        if old_baseline["drivers"]["gcc"]["sha256"] != BASELINE_GCC_SHA256 or any(
                old_hardware[k] != hardware[k] for k in ("AGFI", "driver_bundle_sha256",
                                                        "Chipyard_revision", "FireSim_revision")):
            raise ValueError("prior SPEC observations use another baseline or hardware")
        base = json.loads((run / "baseline-f2/train/evaluation.json").read_text())["times"]
        samples = {b: [] for b in base}
        for path in sorted(run.glob("candidate-???.json")):
            record = json.loads(path.read_text())
            if not record.get("success"):
                continue
            identity = record["compiler"]["compiler_id"]
            if identity not in by_id:
                continue
            for benchmark in samples:
                samples[benchmark].append((math.log(by_id[identity]), math.log(base[benchmark] / record["train_times"][benchmark])))
        transfer.append({"run": str(run), "train_only": True, "benchmarks": {
            b: {"configurations": len(rows), **rank_agreement(rows)} for b, rows in samples.items()}})
    return {"observations": observations, "surrogate_validation": validation_report(observations),
            "spec_transfer_exploratory": transfer,
            "interpretation": "Proxy ranking requires SPEC confirmation; small post-hoc transfer samples are not held-out validation"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screen", type=Path, required=True)
    parser.add_argument("--prior", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.screen, args.prior)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "observations"}, indent=2))


if __name__ == "__main__":
    main()
