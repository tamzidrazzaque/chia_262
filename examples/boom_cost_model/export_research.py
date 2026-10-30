"""Export an allowlist of research measurements, never licensed workloads/logs."""

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import re

from chia.chipyard.cost_model import BASE_COSTS, FLAGS, GCC_REVISION


CAMPAIGNS = {
    "scalar-1": "boom-gcc-opt-20261018",
    "scalar-2": "boom-next-20261020/costs-run-20261021",
    "coordinated": "boom-focused-20261028/run",
    "paired": "boom-diagnosis-20261029/paired",
}
BATCHES = {"history-f2-retry": "history-batch", "boom-f2": "boom-batch",
           "issue-f2": "issue-batch", "mul-f2": "mul-batch"}
BASELINE = "28b629f64ed9797dc198621eb5cfcb63c0a48e17b95c639bada20f14038e77e4"


def read(path):
    """Read one expected JSON artifact."""
    return json.loads(path.read_text())


def proposal_data(record):
    """Keep numerical choices; exclude unverified generated explanations."""
    proposal = record.get("proposal", {})
    compiler = record.get("compiler", {})
    return {"index": record["index"], "success": bool(record.get("success")),
            "compiler_id": compiler.get("compiler_id"),
            "costs": proposal.get("costs", {}),
            "move_profile": proposal.get("move_profile"),
            "train_guest_seconds": record.get("train_times", {}),
            "train_speedup": record.get("speedup"), "estimate": True}


def verified_sample(directory):
    """Export only saved successful simulation/native comparisons and one time."""
    correctness = directory / "correctness.json"
    completion = directory / "completion.json"
    if not completion.exists() or not read(correctness).get("success") or not read(completion).get("success"):
        return None
    files = list((directory / "collected").glob("**/output/*.csv"))
    if len(files) != 1:
        raise ValueError("expected one collected SPEC time CSV")
    with files[0].open() as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 1:
        raise ValueError("expected one collected timing row")
    seconds = float(rows[0]["RealTime"])
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("invalid collected time")
    return {"benchmark": files[0].stem, "guest_seconds": seconds,
            "native_correctness_passed": True, "simulation_completed": True,
            "csv_sha256": hashlib.sha256(files[0].read_bytes()).hexdigest(),
            "correctness_sha256": hashlib.sha256(correctness.read_bytes()).hexdigest()}


def spec_samples(root, campaign, worker_aliases=None):
    """Keep physical-worker pairing and cached observations explicit."""
    samples = []
    for correct in sorted(root.rglob("correctness.json")):
        relative = correct.relative_to(root)
        if "qemu" in relative.parts or not {"train", "ref"}.intersection(relative.parts):
            continue
        directory = correct.parent
        row = verified_sample(directory)
        if row is None:
            continue
        measurement = directory / "measurement.json"
        origin = read(measurement) if measurement.exists() else {}
        role, compiler_id = "unknown", None
        # An evaluation identifies the compiler without copying worker paths.
        for parent in directory.parents:
            if parent == root.parent:
                break
            evaluation = parent / "evaluation.json"
            if evaluation.exists():
                e = read(evaluation)
                compiler_id = e.get("compiler", {}).get("compiler_id")
                role = e.get("kind", "unknown")
                break
        if role == "unknown":
            role = "baseline" if any(p.startswith("baseline") for p in relative.parts) else "candidate"
        candidate = next((int(match[1]) for p in relative.parts
                          if (match := re.match(r"candidate-(\d+)", p))), None)
        if campaign == "paired" and role == "candidate":
            candidate = read(root / "check.json")["candidate_index"]
        # A completed paired sample stores compiler/kind directly in evaluation.
        if role == "baseline" and compiler_id is None:
            compiler_id = BASELINE
        worker = (worker_aliases or {}).get(origin.get("instance_id"))
        if worker is None:
            worker = next((p for p in relative.parts if re.fullmatch(r"worker-\d+", p)), None)
        if worker is None:
            config_path = root / "config.json"
            config = read(config_path) if config_path.exists() else {}
            workers = config.get("fpga_workers", [])
            iid = origin.get("instance_id")
            index = next((i for i, w in enumerate(workers) if w["instance_id"] == iid), None)
            worker = "worker-" + str(index) if index is not None else "historical-worker"
        slot = next((int(m[1]) for p in relative.parts
                     if (m := re.match(r"sample-(\d+)-", p))), None)
        repeat = int(directory.parent.name) if directory.parent.name.isdigit() else None
        samples.append({**row, "campaign": campaign, "inputs": "ref" if "ref" in relative.parts else "train",
            "role": role, "candidate_index": candidate, "compiler_id": compiler_id, "worker": worker,
            "repeat": repeat, "paired_slot": slot, "reused": origin.get("reused", False),
            "cache_metadata_present": measurement.exists(), "measurement_key": origin.get("key"),
            "estimate": True, "source_artifact": relative.as_posix()})
    return samples


def fast_data(root, worker_aliases):
    """Original-kernel observations include ELF hashes to expose duplicate code."""
    samples, batches = [], []
    for experiment, batch_name in BATCHES.items():
        result = read(root / experiment / "result.json")
        batch = root / batch_name
        build = read(batch / "build.json")
        hashes = {}
        for line in (batch / "diagnostics/binaries.sha256").read_text().splitlines():
            sha, name = line.split(maxsplit=1)
            hashes[Path(name.lstrip("*")).name] = sha
        variants = {name: {"compiler_id": record["compiler_id"], "elf_sha256": hashes.get(name)}
                    for name, record in build["variants"].items()}
        batches.append({"experiment": experiment, "success": result["success"], "variants": variants,
            "flags": build["flags"], "kernel_source_sha256": build["source_sha256"],
            "recipe": build["recipe"], "aliases": build.get("aliases", {})})
        for wid, report in result["reports"].items():
            for name, v in report["variants"].items():
                if not v["success"] or not v["FPGA_executed"]:
                    raise ValueError("unvalidated kernel measurement")
                for record in v["records"]:
                    samples.append({"experiment": experiment, "worker": worker_aliases[wid], "variant": name,
                        **variants[name], **{k: record[k] for k in ("kernel", "repeat", "elapsed_ns", "checksum")}})
    return {"batches": batches, "samples": samples,
            "interpretation": "Original redistributable kernels. Identical ELF hashes are not independent code variants; these labels failed to rank SPEC candidates reliably."}


def export(run_root, compiler_build_root, output):
    """Write numeric metadata only; no caller-selected raw files are copied."""
    output.mkdir(parents=True, exist_ok=True)
    worker_aliases = {w["instance_id"]: f"worker-{i}" for i, w in enumerate(
        read(run_root / CAMPAIGNS["paired"] / "workers.json"))}
    campaigns, observations = [], []
    for label, folder in CAMPAIGNS.items():
        root = run_root / folder
        observations.extend(spec_samples(root, label, worker_aliases))
        if label == "paired":
            result = read(root / "result.json")
            summary = [{"worker": worker_aliases[wid], "speedup": v["speedup"], "medians": v["medians"]}
                       for wid, v in result["workers"].items()]
            campaigns.append({"id": label, "complete": result["complete"], "candidate_index": result["candidate_index"],
                "reference_checked": False, "workers": summary, "estimate": True})
            continue
        progress = read(root / "progress.json")
        config = read(root / "config.json")
        result = read(root / "result.json") if (root / "result.json").exists() else {}
        campaigns.append({"id": label, "benchmarks": config["benchmarks"], "repeats": config["repeats"],
            "selection_threshold": config["min_improvement"], "complete": result.get("complete", False),
            "baseline_retained": result.get("baseline_retained", result.get("best", {}).get("compiler_id") == BASELINE
                                            if result.get("best") else None), "estimate": True,
            "reference_checked": result.get("reference_checked", False),
            "threshold_cleared": any(h.get("speedup", 0) >= 1 + config["min_improvement"]
                                     for h in progress["history"] if h.get("success")),
            "history": [proposal_data(h) for h in progress["history"]]})
    coverage = {}
    for label in ("baseline", "candidate-003"):
        base = run_root / "boom-diagnosis-20261029/coverage" / label
        profile = read(base / "profile.json")
        reports = list(base.glob("qemu/*/correctness.json"))
        if not profile["success"] or len(reports) != 1 or not read(reports[0])["success"]:
            raise ValueError("coverage lacks native correctness")
        coverage[label] = {"inputs": "train", "FPGA_executed": False, "flags_added": profile["flags_added"],
            "native_correctness_passed": True, "limitation": profile["limitation"],
            "functions": [{k: f[k] for k in ("name", "execution_count", "blocks", "blocks_executed")}
                          for f in profile["functions"]]}
    analysis = compiler_build_root / "boom-diagnosis-20261029"
    hardware = read(run_root / CAMPAIGNS["coordinated"] / "worker-0/hardware.json")
    provenance = {"compiler": {"gcc_revision": GCC_REVISION, "baseline_gcc_sha256": BASELINE,
                   "model_flags": FLAGS, "spec_fortran_additional_flags": ["-fopenmp", "-DSPEC_OPENMP"],
                   "threads": 1},
                  "hardware": {k: hardware[k] for k in ("AGFI", "AFI", "quintuplet", "shell",
                      "Chipyard_revision", "FireSim_revision", "driver_bundle_sha256", "matching_source_verified")},
                  "BOOM_revision": "5223e44cfeb26f41380057a2eb4d651197475f69",
                  "Speckle_revision": "07f845d381965900b5c1c1f11db8980d1b238f20",
                  "target": "MegaBOOM V3, public FRFCFS/LLC F2 image; no Rocket hardware measurements in this dataset"}
    fast = fast_data(run_root / "boom-fast-20261028", worker_aliases)
    identities = {h["compiler_id"] for c in campaigns for h in c.get("history", [])}
    identities.update(v["compiler_id"] for b in fast["batches"] for v in b["variants"].values())
    models = {BASELINE: {"compiler_id": BASELINE, "gcc_revision": GCC_REVISION,
                        "tuning": "rocket", "costs": BASE_COSTS, "original_installed_compiler": True}}
    allowed = {"compiler_id", "gcc_revision", "baseline_gcc_sha256", "costs", "scheduling", "tuning",
               "model_version", "move_profile", "move_profile_version", "boom_revision", "source_hashes", "diff_sha256"}
    for identity in sorted(identities - {BASELINE}):
        manifest = compiler_build_root / "boom-gcc/compilers" / identity / "cost-model.json"
        if not manifest.exists():
            raise ValueError("compiler manifest missing for a measured model")
        models[identity] = {k: v for k, v in read(manifest).items() if k in allowed}
        models[identity].setdefault("tuning", "rocket")
    data = {"spec-estimates.json": {"estimate": True, "SPEC_reportable_score": False,
                "interpretation": "Non-compliant research estimates: partial suite, train and selected reference inputs, FPGA simulation and custom timing; no official SPEC metric.",
                "campaigns": campaigns, "samples": observations},
            "fast-kernels.json": fast,
            "compiler-models.json": models,
            "coverage-counts.json": coverage,
            "allocation-pressure.json": read(analysis / "allocation/pressure-summary.json"),
            "static-application.json": read(analysis / "application-audit.json"),
            "cross-file-moves.json": read(analysis / "cross-file-audit.json"),
            "floating-opcodes.json": read(analysis / "application-fp-opcodes.json"),
            "provenance.json": provenance}
    for name, value in data.items():
        (output / name).write_text(json.dumps(value, indent=2) + "\n")
    manifest = {"schema_version": 1, "exporter": "examples.boom_cost_model.export_research",
        "files": {name: hashlib.sha256((output / name).read_bytes()).hexdigest() for name in data},
        "excluded": ["SPEC source/ISO/installation", "binaries/root filesystems", "licensed inputs/reference outputs",
                     "SPEC program assembly/IR/gcov notes/data", "raw logs/Claude sessions", "credentials/site configurations"],
        "spec_publication_rules": "https://www.spec.org/cpu2017/Docs/runrules.html"}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return {"spec_samples": len(observations), "kernel_samples": len(data["fast-kernels.json"]["samples"])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--compiler-build-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(export(args.run_root, args.compiler_build_root, args.output))


if __name__ == "__main__":
    main()
