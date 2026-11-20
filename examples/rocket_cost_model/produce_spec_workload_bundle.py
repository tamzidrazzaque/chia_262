"""Create private role-1/role-2 bundles for an already screened SPEC workload."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from examples.rocket_cost_model.saturn_spec.bundle import (
    BASELINE_GCC_SHA, GCC_REVISION, TARGET, inspect_elf, sha,
)

SOURCE = "unchanged SPEC CPU2017 source"
SCALAR_FLAGS = "-march=rv64gc -mabi=lp64d -mtune=rocket -fno-tree-loop-vectorize -fno-tree-slp-vectorize"
VECTOR_FLAGS = "-march=rv64gcv_zvbb -mabi=lp64d -mtune=rocket -mrvv-vector-bits=scalable -fvect-cost-model=dynamic -fopt-info-vec-all"


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def make_role(spec: Path, evidence: Path, out: Path, toolchain: Path,
              readelf: Path, objdump: Path, benchmark: str, role: str, size: str) -> Path:
    label = "saturn_role1_scalar" if role == "1-scalar" else "saturn_role2_generic_vector"
    root = spec / "benchspec/CPU" / benchmark
    run = max((root / "run").glob(f"run_base_{size}_{label}-64.*"), key=lambda p: p.stat().st_mtime_ns)
    program = benchmark.split(".", 1)[1]
    binary = run / f"{program}_base.{label}-64"
    inputs = [p for p in run.iterdir() if p.is_file() and p.name not in {
        binary.name, "stdout.txt", "stderr.txt", "compare.out", "compare.err",
        "compare.cmd", "compare.stdout", "speccmds.cmd", "speccmds.out",
        "speccmds.err", "speccmds.stdout", "control", "test.out.cmp",
        "mcf.out.cmp", "deepsjeng.out.cmp",
    } and not p.name.endswith(".cmp") and p.suffix not in {".err", ".cmd"}]
    input_file = next((p for p in inputs if p.name not in {"mcf.out", "test.out", "deepsjeng.out"}), None)
    if input_file is None:
        raise ValueError(f"could not identify SPEC input in {run}")
    # SPEC keeps the golden output directory alongside the run directory.  Use
    # that directory to distinguish the workload's output (e.g. ``test.out``)
    # from harness diagnostics such as ``speccmds.out``.
    golden_dir = root / "data" / size / "output"
    golden_names = {p.name for p in golden_dir.iterdir() if p.is_file()}
    outputs = [p for p in run.glob("*.out") if p.name in golden_names]
    output_file = next((p for p in outputs if p.name != input_file.name), None)
    if output_file is None:
        raise ValueError(f"could not identify executable output in {run}")
    reference = root / "data" / size / "output" / output_file.name
    if not all(p.is_file() for p in (binary, input_file, output_file, reference)):
        raise ValueError("missing validated SPEC payload/reference")
    log = evidence / f"{benchmark}-{size}-{label}-validate.log"
    if not log.is_file():
        raise ValueError(f"missing validation log: {log}")
    audit = inspect_elf(binary, readelf, objdump)
    out.mkdir(parents=True, mode=0o700, exist_ok=False)
    for dest, src in {
        "payload/program": binary, "payload/" + input_file.name: input_file,
        "reference/" + output_file.name: reference, "metadata/validation.log": log,
    }.items():
        (out / dest).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out / dest)
    flags = SCALAR_FLAGS if role == "1-scalar" else VECTOR_FLAGS
    compiler = {"gcc_version": "15.1.0", "gcc_revision": GCC_REVISION,
                "compiler_sha256": BASELINE_GCC_SHA, "role": role,
                "target_flags": flags, "candidate_id": None, "snapshot_id": None}
    write_json(out / "metadata/compiler.json", compiler)
    isa = {"elf_sha256": sha(out / "payload/program"), "riscv_arch": audit["riscv_arch"],
           "abi": "lp64d", "linkage": "static", "vlen_bits": 256,
           "dlen_bits": 128, "static_rvv_instruction_count": audit["static_rvv_instruction_count"]}
    write_json(out / "metadata/isa.json", isa)
    invocation = {"argv": ["./program", input_file.name], "stdin": None,
                  "stdout": output_file.name, "stderr": "stderr.txt"}
    validation = {"status": "passed", "spec_validation": "passed", "backend": "qemu",
                  "role": role, "benchmark": benchmark, "size": size,
                  "input_id": f"{benchmark.replace('.', '-')}-{size}",
                  "source_variant": SOURCE, "target_vlen": 256, "target_dlen": 128,
                  "elf_sha256": sha(out / "payload/program"),
                  "invocation_sha256": hashlib.sha256(json.dumps(invocation, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                  "compiler_manifest_sha256": sha(out / "metadata/compiler.json"),
                  "isa_metadata_sha256": sha(out / "metadata/isa.json"),
                  "inputs_sha256": {input_file.name: sha(out / "payload" / input_file.name)},
                  "expected_outputs_sha256": {output_file.name: sha(out / "reference" / output_file.name)},
                  "validation_log": "metadata/validation.log"}
    write_json(out / "metadata/validation.json", validation)
    files = {p.relative_to(out).as_posix(): sha(p) for p in out.rglob("*") if p.is_file()}
    manifest = {"schema_version": 1, "role": role, "candidate_id": None,
                "benchmark": benchmark, "input_id": validation["input_id"], "size": size,
                "source_variant": SOURCE, "target": TARGET,
                "compiler_manifest": "metadata/compiler.json", "isa_metadata": "metadata/isa.json",
                "validation_manifest": "metadata/validation.json", "executable": "payload/program",
                "inputs": {input_file.name: "payload/" + input_file.name},
                "expected_outputs": {output_file.name: "reference/" + output_file.name}, **invocation,
                "files_sha256": dict(sorted(files.items()))}
    write_json(out / "manifest.json", manifest)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec-dir", type=Path, required=True)
    ap.add_argument("--evidence", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--toolchain", type=Path, required=True)
    ap.add_argument("--readelf", type=Path,
                    default=Path("/scratch/trazzaque/riscv-gnu-local/bin/riscv64-unknown-elf-readelf"))
    ap.add_argument("--objdump", type=Path,
                    default=Path("/scratch/trazzaque/riscv-gnu-local/bin/riscv64-unknown-elf-objdump"))
    ap.add_argument("--benchmark", required=True)
    ap.add_argument("--size", default="test")
    args = ap.parse_args()
    for role in ("1-scalar", "2-generic-vector"):
        make_role(args.spec_dir, args.evidence, args.out / role, args.toolchain,
                  args.readelf, args.objdump, args.benchmark, role, args.size)


if __name__ == "__main__":
    main()
