"""Create a private, immutable roles 1/2 SPEC workload handoff for Saturn.

The archive contains licensed binaries, inputs, and the reference output, so it
must remain outside Git.  A content-addressed receipt lets the F2 manager reject
an altered or mismatched handoff before staging it into FireMarshal.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tarfile
import tempfile

from examples.rocket_cost_model.spec_vector_baseline import (
    BENCHMARK,
    TARGET_CONFIG,
    TARGET_DLEN,
    TARGET_FIRESIM_CONFIG,
    TARGET_VLEN,
    role_settings,
    sha256,
    validate_exchange2_output,
)


def _add(archive: tarfile.TarFile, source: Path, destination: str,
         executable: bool = False) -> None:
    info = archive.gettarinfo(str(source), arcname=destination)
    info.uid = info.gid = 0
    info.uname = info.gname = "root"
    info.mtime = 0
    info.mode = 0o755 if executable else 0o644
    with source.open("rb") as stream:
        archive.addfile(info, stream)


def create_bundle(spec_dir: Path, evidence: Path, output: Path,
                  benchmark: str = BENCHMARK, size: str = "test") -> dict:
    """Package already validated private artifacts and return a public receipt."""
    if benchmark != BENCHMARK:
        raise ValueError(f"unsupported workload: {benchmark}")
    program = benchmark.split(".", 1)[1]
    roles = {}
    for role in ("1-scalar", "2-generic-vector"):
        label, flags, _ = role_settings(role)
        metadata_path = evidence / f"{benchmark}-{size}-{label}-validate.json"
        if not metadata_path.is_file():
            raise ValueError(f"missing validation metadata for {role}")
        metadata = json.loads(metadata_path.read_text())
        validation = validate_exchange2_output(spec_dir, benchmark, size, label)
        if metadata.get("output_validation") != validation:
            raise ValueError(f"stale output validation metadata for {role}")
        binary = spec_dir / "benchspec/CPU" / benchmark / "exe" / f"{program}_base.{label}-64"
        if not binary.is_file():
            raise ValueError(f"missing validated executable for {role}")
        roles[role] = {
            "label": label,
            "target_flags": flags,
            "binary": binary,
            "binary_sha256": sha256(binary),
            "archive_path": f"roles/{role}/{program}",
        }

    run_dir = max(
        (spec_dir / "benchspec/CPU" / benchmark / "run").glob(
            f"run_base_{size}_{roles['1-scalar']['label']}-64.*"
        ),
        key=lambda path: path.stat().st_mtime_ns,
    )
    reference = spec_dir / "benchspec/CPU/548.exchange2_r/data" / size / "output/s.txt"
    private_files = {
        "inputs/puzzles.txt": run_dir / "puzzles.txt",
        "inputs/control": run_dir / "control",
        "expected/s.txt": reference,
    }
    for destination, source in private_files.items():
        if not source.is_file():
            raise ValueError(f"missing private workload file for {destination}")

    manifest = {
        "schema_version": 1,
        "workload": {"benchmark": benchmark, "size": size, "source": "SPEC CPU2017"},
        "target": {
            "config": TARGET_CONFIG,
            "firesim_config": TARGET_FIRESIM_CONFIG,
            "vlen": TARGET_VLEN,
            "dlen": TARGET_DLEN,
        },
        "roles": {
            role: {key: value for key, value in details.items() if key != "binary"}
            for role, details in roles.items()
        },
        "files": {
            destination: {"sha256": sha256(source), "bytes": source.stat().st_size}
            for destination, source in private_files.items()
        },
        "measurement_policy": {
            "qemu_results_are_correctness_only": True,
            "performance_backend": "exact Saturn F2 target",
            "paired_roles": ["1-scalar", "2-generic-vector"],
        },
    }

    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
        manifest_path = Path(temporary) / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        with tarfile.open(output, "w", format=tarfile.PAX_FORMAT) as archive:
            _add(archive, manifest_path, "manifest.json")
            for details in roles.values():
                _add(archive, details["binary"], details["archive_path"], executable=True)
            for destination, source in private_files.items():
                _add(archive, source, destination)

    receipt = {
        "schema_version": 1,
        "bundle": output.name,
        "bundle_sha256": sha256(output),
        "bundle_bytes": output.stat().st_size,
        "manifest_sha256": hashlib.sha256(
            (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
        ).hexdigest(),
        "contains_licensed_spec_material": True,
        "publishable": False,
        "target": manifest["target"],
        "roles": manifest["roles"],
    }
    receipt_path = output.with_suffix(output.suffix + ".receipt.json")
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec-dir", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--benchmark", default=BENCHMARK)
    parser.add_argument("--size", choices=("test", "train"), default="test")
    args = parser.parse_args()
    receipt = create_bundle(
        args.spec_dir.resolve(), args.evidence.resolve(), args.output.resolve(),
        args.benchmark, args.size,
    )
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
