"""Produce complete private per-role SPEC directories for Saturn intake.

The output contains licensed SPEC material and validation logs. Keep it outside
Git and transfer it only to the private manager intake described in
SATURN_SPEC_LANE.md.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile

from examples.rocket_cost_model.saturn_spec.bundle import (
    BASELINE_GCC_SHA,
    EXCHANGE2_BASELINES,
    GCC_REVISION,
    TARGET,
    canonical,
    inspect_elf,
    sha,
)
from examples.rocket_cost_model.spec_vector_baseline import (
    BENCHMARK,
    TARGET_DLEN,
    TARGET_VLEN,
    role_settings,
    validate_exchange2_output,
)

SOURCE = "unchanged SPEC CPU2017 source"
INPUT_ID = "exchange2-test-1"


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def create_role_directory(spec_dir: Path, evidence: Path, output_root: Path,
                          toolchain: Path, role: str,
                          benchmark: str = BENCHMARK, size: str = "test") -> tuple[Path, str]:
    """Create one content-addressed directory satisfying manager intake."""
    if role not in ("1-scalar", "2-generic-vector"):
        raise ValueError("this producer freezes only baseline roles 1 and 2")
    if benchmark != BENCHMARK or size != "test":
        raise ValueError("this producer currently validates only Exchange2 test")
    label, flags, _ = role_settings(role)
    program = benchmark.split(".", 1)[1]
    binary = spec_dir / "benchspec/CPU" / benchmark / "exe" / f"{program}_base.{label}-64"
    metadata_path = evidence / f"{benchmark}-{size}-{label}-validate.json"
    validation_log = evidence / f"{benchmark}-{size}-{label}-validate.log"
    if not all(path.is_file() for path in (binary, metadata_path, validation_log)):
        raise ValueError(f"missing validated private artifacts for {role}")
    if sha(binary) != EXCHANGE2_BASELINES[role]:
        raise ValueError(f"frozen baseline ELF identity changed for {role}")
    metadata = json.loads(metadata_path.read_text())
    expected_validation = validate_exchange2_output(spec_dir, benchmark, size, label)
    if metadata.get("output_validation") != expected_validation:
        raise ValueError(f"stale exact-output evidence for {role}")
    expected_metadata = {
        "role": role,
        "benchmark": benchmark,
        "size": size,
        "source_variant": SOURCE,
        "target_flags": flags,
        "target_vlen": TARGET_VLEN,
        "target_dlen": TARGET_DLEN,
        "gcc_sha256": BASELINE_GCC_SHA,
    }
    if any(metadata.get(key) != value for key, value in expected_metadata.items()):
        raise ValueError(f"validation metadata identity changed for {role}")

    readelf = toolchain / "bin/riscv64-unknown-linux-gnu-readelf"
    objdump = toolchain / "bin/riscv64-unknown-linux-gnu-objdump"
    compiler = toolchain / "bin/riscv64-unknown-linux-gnu-gcc"
    if not readelf.is_file() or not objdump.is_file() or not compiler.is_file():
        raise ValueError("missing pinned compiler or ELF audit tools")
    if sha(compiler) != BASELINE_GCC_SHA:
        raise ValueError("stock compiler identity changed")
    audit = inspect_elf(binary, readelf, objdump)

    run_root = spec_dir / "benchspec/CPU" / benchmark / "run"
    runs = list(run_root.glob(f"run_base_{size}_{label}-64.*"))
    if not runs:
        raise ValueError(f"missing validated run directory for {role}")
    run = max(runs, key=lambda path: path.stat().st_mtime_ns)
    sources = {
        "payload/program": binary,
        "payload/puzzles.txt": run / "puzzles.txt",
        "payload/control": run / "control",
        "reference/s.txt": spec_dir / "benchspec/CPU/548.exchange2_r/data/test/output/s.txt",
        "metadata/validation.log": validation_log,
    }
    if not all(path.is_file() for path in sources.values()):
        raise ValueError(f"missing input, reference, or log for {role}")

    output_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{role}-", dir=output_root))
    try:
        for destination, source in sources.items():
            target = temporary / destination
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            target.chmod(0o700 if destination == "payload/program" else 0o600)

        compiler_metadata = {
            "gcc_version": "15.1.0",
            "gcc_revision": GCC_REVISION,
            "role": role,
            "target_flags": flags,
            "compiler_sha256": BASELINE_GCC_SHA,
            "snapshot_id": None,
            "candidate_id": None,
        }
        isa = {
            "elf_sha256": sha(binary),
            "riscv_arch": audit["riscv_arch"],
            "abi": "lp64d",
            "linkage": "static",
            "vlen_bits": TARGET_VLEN,
            "dlen_bits": TARGET_DLEN,
            "static_rvv_instruction_count": audit["static_rvv_instruction_count"],
        }
        compiler_path = temporary / "metadata/compiler.json"
        isa_path = temporary / "metadata/isa.json"
        _write_json(compiler_path, compiler_metadata)
        _write_json(isa_path, isa)
        compiler_path.chmod(0o600)
        isa_path.chmod(0o600)

        argv = ["./program", "0"]
        invocation = {
            "argv": argv,
            "stdin": None,
            "stdout": "exchange2.txt",
            "stderr": "exchange2.err",
        }
        validation = {
            "status": "passed",
            "spec_validation": "passed",
            "backend": "qemu",
            "role": role,
            "benchmark": benchmark,
            "size": size,
            "input_id": INPUT_ID,
            "source_variant": SOURCE,
            "target_vlen": TARGET_VLEN,
            "target_dlen": TARGET_DLEN,
            "elf_sha256": sha(temporary / "payload/program"),
            "compiler_manifest_sha256": sha(compiler_path),
            "isa_metadata_sha256": sha(isa_path),
            "invocation_sha256": canonical(invocation),
            "inputs_sha256": {
                "puzzles.txt": sha(temporary / "payload/puzzles.txt"),
                "control": sha(temporary / "payload/control"),
            },
            "expected_outputs_sha256": {
                "s.txt": sha(temporary / "reference/s.txt"),
            },
            "validation_log": "metadata/validation.log",
        }
        validation_path = temporary / "metadata/validation.json"
        _write_json(validation_path, validation)
        validation_path.chmod(0o600)

        files = {
            path.relative_to(temporary).as_posix(): sha(path)
            for path in temporary.rglob("*") if path.is_file()
        }
        manifest = {
            "schema_version": 1,
            "role": role,
            "candidate_id": None,
            "benchmark": benchmark,
            "input_id": INPUT_ID,
            "size": size,
            "source_variant": SOURCE,
            "target": TARGET,
            "compiler_manifest": "metadata/compiler.json",
            "isa_metadata": "metadata/isa.json",
            "validation_manifest": "metadata/validation.json",
            "executable": "payload/program",
            "inputs": {
                "puzzles.txt": "payload/puzzles.txt",
                "control": "payload/control",
            },
            "expected_outputs": {"s.txt": "reference/s.txt"},
            **invocation,
            "files_sha256": dict(sorted(files.items())),
        }
        manifest_path = temporary / "manifest.json"
        _write_json(manifest_path, manifest)
        manifest_path.chmod(0o600)
        identity = sha(manifest_path)
        destination = output_root / identity
        if destination.exists():
            raise FileExistsError(f"content-addressed bundle already exists: {destination}")
        os.rename(temporary, destination)
        return destination, identity
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec-dir", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--toolchain", type=Path, required=True)
    parser.add_argument("--role", choices=("1-scalar", "2-generic-vector"), required=True)
    args = parser.parse_args()
    destination, identity = create_role_directory(
        args.spec_dir.resolve(), args.evidence.resolve(), args.output_root.resolve(),
        args.toolchain.resolve(), args.role,
    )
    print(json.dumps({"directory": str(destination), "manifest_sha256": identity},
                     sort_keys=True))


if __name__ == "__main__":
    main()
