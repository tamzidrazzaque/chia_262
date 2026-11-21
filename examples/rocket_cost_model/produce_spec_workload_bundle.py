"""Create private role-1/role-2 bundles for an already screened SPEC workload."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from examples.rocket_cost_model.spec_vector_baseline import role_settings

from examples.rocket_cost_model.saturn_spec.bundle import (
    BASELINE_GCC_SHA, GCC_REVISION, TARGET, inspect_elf, sha,
)

SOURCE = "unchanged SPEC CPU2017 source"
SCALAR_FLAGS = "-march=rv64gc -mabi=lp64d -mtune=rocket -fno-tree-loop-vectorize -fno-tree-slp-vectorize"
VECTOR_FLAGS = "-march=rv64gcv_zvbb -mabi=lp64d -mtune=rocket -mrvv-vector-bits=scalable -fvect-cost-model=dynamic -fopt-info-vec-all"


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def make_role(spec: Path, evidence: Path, out: Path, toolchain: Path,
              readelf: Path, objdump: Path, benchmark: str, role: str, size: str,
              candidate_id: str | None = None, candidate_manifest: Path | None = None) -> Path:
    label, flags, _ = role_settings(role, candidate_id)
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
    if input_file is None and benchmark != "644.nab_s":
        raise ValueError(f"could not identify SPEC input in {run}")
    # SPEC keeps the golden output directory alongside the run directory.  Use
    # that directory to distinguish the workload's output (e.g. ``test.out``)
    # from harness diagnostics such as ``speccmds.out``.
    # NAB's reference package is laid out differently from most SPEC
    # workloads: its input is a directory and its validated output is
    # hkrdenq.out.  Preserve that contract exactly; the scalar validated run
    # is the paired oracle because this installation has no data/test/output
    # directory for NAB.
    nab = benchmark == "644.nab_s"
    if nab:
        input_dir = run / "hkrdenq"
        output_file = run / "hkrdenq.out"
        if not input_dir.is_dir():
            raise ValueError(f"missing NAB input directory: {input_dir}")
        input_files = sorted(p for p in input_dir.rglob("*") if p.is_file())
        if not input_files:
            raise ValueError(f"empty NAB input directory: {input_dir}")
        if role == "1-scalar":
            oracle = output_file
        else:
            scalar_runs = sorted((root / "run").glob("run_base_" + size + "_saturn_role1_scalar-64.*"),
                                 key=lambda p: p.stat().st_mtime_ns)
            oracle = scalar_runs[-1] / "hkrdenq.out" if scalar_runs else None
            if oracle is None or not oracle.is_file() or output_file.read_bytes() != oracle.read_bytes():
                raise ValueError("NAB vector output differs from validated scalar oracle")
    elif (root / "data" / size / "output").is_dir():
        golden_dir = root / "data" / size / "output"
        golden_names = {p.name for p in golden_dir.iterdir() if p.is_file()}
        outputs = [p for p in run.glob("*.out") if p.name in golden_names]
        output_file = next((p for p in outputs if p.name != input_file.name), None)
        oracle = golden_dir / output_file.name if output_file is not None else None
    else:
        # Some SPEC installations retain the validated run tree but omit the
        # benchmark data/output tree.  Use the independently validated scalar
        # run as the paired oracle and require every non-scalar role to match
        # it byte-for-byte; this does not invent or normalize output.
        output_name = {"605.mcf_s": "mcf.out"}.get(benchmark)
        if output_name is None:
            raise ValueError(f"no trusted output layout for {benchmark}")
        output_file = run / output_name
        scalar_runs = sorted((root / "run").glob("run_base_" + size + "_saturn_role1_scalar-64.*"),
                             key=lambda p: p.stat().st_mtime_ns)
        oracle = scalar_runs[-1] / output_name if scalar_runs else None
        if role != "1-scalar" and (oracle is None or not oracle.is_file() or output_file.read_bytes() != oracle.read_bytes()):
            raise ValueError(f"{benchmark} output differs from validated scalar oracle")
    if output_file is None:
        raise ValueError(f"could not identify executable output in {run}")
    reference = oracle
    if not all(p.is_file() for p in (binary, output_file, reference)):
        raise ValueError("missing validated SPEC payload/reference")
    log = evidence / f"{benchmark}-{size}-{label}-validate.log"
    if not log.is_file():
        raise ValueError(f"missing validation log: {log}")
    audit = inspect_elf(binary, readelf, objdump)
    out.mkdir(parents=True, mode=0o700, exist_ok=False)
    input_dest_name = "input.in" if benchmark == "605.mcf_s" else (None if nab else input_file.name)
    stdout_name = "stdout.txt" if benchmark == "605.mcf_s" else output_file.name
    sources = {"payload/program": binary, "reference/" + output_file.name: reference,
               "metadata/validation.log": log}
    if nab:
        sources.update({"payload/hkrdenq/" + p.relative_to(input_dir).as_posix(): p
                        for p in input_files})
    else:
        sources["payload/" + input_dest_name] = input_file
    for dest, src in sources.items():
        (out / dest).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out / dest)
    flags = SCALAR_FLAGS if role == "1-scalar" else VECTOR_FLAGS
    full_candidate = None
    if candidate_manifest is not None:
        full_candidate = json.loads(candidate_manifest.read_text())["candidate_id"]
    compiler = {"gcc_version": "15.1.0", "gcc_revision": GCC_REVISION,
                "compiler_sha256": sha(toolchain / "bin/riscv64-unknown-linux-gnu-gcc"),
                "role": role, "target_flags": flags,
                "candidate_id": full_candidate, "snapshot_id": full_candidate}
    if role != "3-saturn-aware":
        compiler["compiler_sha256"] = BASELINE_GCC_SHA
        compiler["candidate_id"] = None
        compiler["snapshot_id"] = None
    write_json(out / "metadata/compiler.json", compiler)
    isa = {"elf_sha256": sha(out / "payload/program"), "riscv_arch": audit["riscv_arch"],
           "abi": "lp64d", "linkage": "static", "vlen_bits": 256,
           "dlen_bits": 128, "static_rvv_instruction_count": audit["static_rvv_instruction_count"]}
    write_json(out / "metadata/isa.json", isa)
    if nab:
        invocation = {"argv": ["./program", "hkrdenq", "1930344093", "1000"], "stdin": None,
                      "stdout": output_file.name, "stderr": "stderr.txt"}
        input_map = {"hkrdenq/" + p.relative_to(input_dir).as_posix():
                     "payload/hkrdenq/" + p.relative_to(input_dir).as_posix() for p in input_files}
    else:
        invocation = {"argv": ["./program", input_dest_name], "stdin": None,
                  "stdout": stdout_name, "stderr": "stderr.txt"}
        input_map = {input_dest_name: "payload/" + input_dest_name}
    input_id = (f"{benchmark.split('.')[0]}-{benchmark.split('.')[1].rsplit('_', 1)[0]}-{size}"
                if benchmark == "605.mcf_s" else f"{benchmark.replace('.', '-')}-{size}")
    validation = {"status": "passed", "spec_validation": "passed", "backend": "qemu",
                  "role": role, "benchmark": benchmark, "size": size,
                  "input_id": input_id,
                  "source_variant": SOURCE, "target_vlen": 256, "target_dlen": 128,
                  "elf_sha256": sha(out / "payload/program"),
                  "invocation_sha256": hashlib.sha256(json.dumps(invocation, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                  "compiler_manifest_sha256": sha(out / "metadata/compiler.json"),
                  "isa_metadata_sha256": sha(out / "metadata/isa.json"),
                  "inputs_sha256": {k: sha(out / v) for k, v in input_map.items()},
                  "expected_outputs_sha256": {output_file.name: sha(out / "reference" / output_file.name)},
                  "validation_log": "metadata/validation.log"}
    write_json(out / "metadata/validation.json", validation)
    files = {p.relative_to(out).as_posix(): sha(p) for p in out.rglob("*") if p.is_file()}
    manifest = {"schema_version": 1, "role": role, "candidate_id": candidate_id,
                "benchmark": benchmark, "input_id": validation["input_id"], "size": size,
                "source_variant": SOURCE, "target": TARGET,
                "compiler_manifest": "metadata/compiler.json", "isa_metadata": "metadata/isa.json",
                "validation_manifest": "metadata/validation.json", "executable": "payload/program",
                "inputs": input_map,
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
    ap.add_argument("--role", choices=("1-scalar", "2-generic-vector", "3-saturn-aware"))
    ap.add_argument("--candidate-id")
    ap.add_argument("--candidate-manifest", type=Path)
    args = ap.parse_args()
    roles = (args.role,) if args.role else ("1-scalar", "2-generic-vector")
    if args.role == "3-saturn-aware" and (not args.candidate_id or not args.candidate_manifest):
        ap.error("role 3 requires --candidate-id and --candidate-manifest")
    for role in roles:
        make_role(args.spec_dir, args.evidence, args.out / role, args.toolchain,
                  args.readelf, args.objdump, args.benchmark, role, args.size,
                  args.candidate_id, args.candidate_manifest)


if __name__ == "__main__":
    main()
