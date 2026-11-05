"""Run the real unchanged-SPEC roles 1-3 preparation loop through CHIA.

The graph builds immutable role-3 GCC frontends, builds and validates licensed
SPEC CPU2017 privately, and audits final ELF files. QEMU is a correctness gate;
this graph deliberately reports no Saturn performance score until an exact
Rocket plus Saturn timing backend is connected.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import ray

from chia.base.ChiaFunction import ChiaFunction, get
from examples.rocket_cost_model.spec_vector_baseline import (
    TARGET_CONFIG,
    TARGET_DLEN,
    TARGET_FIRESIM_CONFIG,
    TARGET_VLEN,
    render_config,
    role_settings,
    sha256,
    validated,
)
from examples.rocket_cost_model.vector_cost_model import build_candidate, proposal


@ChiaFunction(num_cpus=4, max_retries=0)
def build_candidate_task(root: str, baseline_prefix: str, proposal_path: str,
                         jobs: int) -> dict:
    """Build one content-addressed GCC frontend snapshot on the CHIA worker."""
    selected = proposal(json.loads(Path(proposal_path).read_text()))
    return build_candidate(Path(root), Path(baseline_prefix), selected, jobs)


def _audit_elf(binary: Path, objdump: Path, readelf: Path) -> dict:
    if not binary.is_file():
        raise RuntimeError(f"SPEC executable was not produced: {binary}")
    total = 0
    vector = 0
    mnemonics: dict[str, int] = {}
    process = subprocess.Popen(
        [str(objdump), "-d", str(binary)], stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
    )
    assert process.stdout is not None
    for line in process.stdout:
        fields = line.split()
        if len(fields) < 3 or not fields[0].endswith(":"):
            continue
        total += 1
        mnemonic = fields[2]
        if re.fullmatch(r"v[a-z0-9.]+", mnemonic):
            vector += 1
            mnemonics[mnemonic] = mnemonics.get(mnemonic, 0) + 1
    stderr = process.stderr.read() if process.stderr else ""
    if process.wait() or stderr:
        raise RuntimeError(f"objdump failed for private SPEC binary: {stderr.strip()}")
    attributes = subprocess.check_output([str(readelf), "-A", str(binary)], text=True)
    arch = re.search(r'Tag_RISCV_arch: "([^"]+)"', attributes)
    if not arch:
        raise RuntimeError("final SPEC ELF has no RISC-V architecture attribute")
    return {
        "sha256": sha256(binary),
        "static_instruction_count": total,
        "static_rvv_instruction_count": vector,
        "static_rvv_mnemonics": dict(sorted(mnemonics.items())),
        "riscv_arch": arch.group(1),
    }


def _verify_reusable_role(output: Path, gcc_root: Path, speckle: Path,
                          qemu: Path, role: str, benchmark: str, size: str,
                          label: str, target_flags: str, vector_qemu: bool,
                          candidate_id: str | None) -> None:
    """Reuse a baseline only when all recorded identities still match."""
    compiler = gcc_root / "bin/riscv64-unknown-linux-gnu-gcc"
    for action in ("build", "validate"):
        stem = f"{benchmark}-{size}-{label}-{action}"
        metadata_path = output / f"{stem}.json"
        log = output / f"{stem}.log"
        if not metadata_path.is_file() or not log.is_file():
            raise RuntimeError(f"cannot resume {role}; missing private {action} evidence")
        metadata = json.loads(metadata_path.read_text())
        expected = {
            "benchmark": benchmark,
            "size": size,
            "role": role,
            "candidate_id": candidate_id,
            "action": action,
            "source_variant": "unchanged SPEC CPU2017 source",
            "target_flags": target_flags,
            "target_config": TARGET_CONFIG,
            "target_firesim_config": TARGET_FIRESIM_CONFIG,
            "target_vlen": TARGET_VLEN,
            "target_dlen": TARGET_DLEN,
            "gcc_sha256": sha256(compiler),
            "qemu_sha256": sha256(qemu),
        }
        for key, value in expected.items():
            if metadata.get(key) != value:
                raise RuntimeError(f"cannot resume {role}; {key} identity changed")
        config = Path(metadata["config"])
        expected_config = render_config(
            (speckle / "riscv.cfg").read_text(), label, target_flags, qemu,
            vector_qemu,
        )
        expected_hash = hashlib.sha256(expected_config.encode()).hexdigest()
        if not config.is_file() or metadata.get("config_sha256") != expected_hash \
                or not config.read_text().startswith(expected_config):
            raise RuntimeError(f"cannot resume {role}; generated config identity changed")
    validate_log = output / f"{benchmark}-{size}-{label}-validate.log"
    if not validated(validate_log.read_text(), benchmark, size):
        raise RuntimeError(f"cannot resume {role}; SPEC validation evidence is absent")


@ChiaFunction(num_cpus=1, max_retries=0)
def run_role_task(repo: str, spec_dir: str, gcc_root: str, toolchain_root: str,
                  speckle: str, qemu: str, output: str, role: str,
                  benchmark: str, size: str, candidate_id: str | None = None,
                  candidate_manifest: str | None = None,
                  reuse_validated: bool = False) -> dict:
    """Build, validate, and audit one real private SPEC role."""
    script = Path(repo) / "examples/rocket_cost_model/spec_vector_baseline.py"
    common = [
        sys.executable, str(script), "--spec-dir", spec_dir, "--gcc-root", gcc_root,
        "--speckle", speckle, "--qemu", qemu, "--out", output, "--role", role,
        "--benchmark", benchmark, "--size", size,
    ]
    if candidate_id and candidate_manifest:
        common += ["--candidate-id", candidate_id, "--candidate-manifest", candidate_manifest]
    label, flags, vector_qemu = role_settings(role, candidate_id)
    if reuse_validated:
        _verify_reusable_role(
            Path(output), Path(gcc_root), Path(speckle), Path(qemu), role,
            benchmark, size, label, flags, vector_qemu, candidate_id,
        )
    else:
        environment = os.environ.copy()
        for action in ("build", "validate"):
            result = subprocess.run(
                [*common, "--action", action], env=environment, capture_output=True,
                text=True, check=False,
            )
            if result.returncode:
                raise RuntimeError(
                    f"{role} {action} failed; inspect private logs. "
                    f"runner output: {result.stdout.strip()} {result.stderr.strip()}"
                )
    log = Path(output) / f"{benchmark}-{size}-{label}-validate.log"
    if not validated(log.read_text(), benchmark, size):
        raise RuntimeError(f"{role} lacks SPEC's explicit success line; inspect {log}")
    program = benchmark.split(".", 1)[1]
    binary = Path(spec_dir) / "benchspec/CPU" / benchmark / "exe" / f"{program}_base.{label}-64"
    tools = Path(toolchain_root) / "bin"
    audit = _audit_elf(
        binary, tools / "riscv64-unknown-linux-gnu-objdump",
        tools / "riscv64-unknown-linux-gnu-readelf",
    )
    if role == "1-scalar" and audit["static_rvv_instruction_count"]:
        raise RuntimeError("role 1 final ELF unexpectedly contains RVV instructions")
    if role != "1-scalar" and not audit["static_rvv_instruction_count"]:
        raise RuntimeError(f"{role} final ELF contains no RVV instructions")
    return {
        "role": role,
        "candidate_id": candidate_id,
        "source_variant": "unchanged SPEC CPU2017 source",
        "benchmark": benchmark,
        "size": size,
        "target_flags": flags,
        "target_config": TARGET_CONFIG,
        "target_firesim_config": TARGET_FIRESIM_CONFIG,
        "target_vlen": TARGET_VLEN,
        "target_dlen": TARGET_DLEN,
        "validated": True,
        "elf": audit,
        "qemu_correctness_only": True,
        "target_performance_result": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--spec-dir", type=Path, required=True)
    parser.add_argument("--baseline-prefix", type=Path, required=True)
    parser.add_argument("--compiler-root", type=Path, required=True)
    parser.add_argument("--proposal", type=Path, required=True)
    parser.add_argument("--speckle", type=Path, required=True)
    parser.add_argument("--qemu", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--benchmark", default="648.exchange2_s")
    parser.add_argument("--size", choices=("test", "train"), default="test")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--ray-temp", type=Path, required=True)
    parser.add_argument("--reuse-validated-baselines", action="store_true")
    args = parser.parse_args()
    paths = {
        name: str(getattr(args, name).resolve()) for name in (
            "repo", "spec_dir", "baseline_prefix", "compiler_root", "proposal",
            "speckle", "qemu", "out", "ray_temp",
        )
    }
    Path(paths["out"]).mkdir(mode=0o700, parents=True, exist_ok=True)
    Path(paths["ray_temp"]).mkdir(mode=0o700, parents=True, exist_ok=True)
    bind_ip = os.environ.get("CHIA_LOOPBACK_BIND_IP", "127.0.0.1")
    ray.init(
        num_cpus=max(4, args.jobs), include_dashboard=False,
        _node_ip_address=bind_ip, _temp_dir=paths["ray_temp"],
    )
    try:
        common = (
            paths["repo"], paths["spec_dir"], paths["baseline_prefix"],
            paths["baseline_prefix"], paths["speckle"], paths["qemu"],
            paths["out"],
        )
        role1 = get(run_role_task.chia_remote(
            *common, "1-scalar", args.benchmark, args.size, None, None,
            args.reuse_validated_baselines,
        ))
        role2 = get(run_role_task.chia_remote(
            *common, "2-generic-vector", args.benchmark, args.size, None, None,
            args.reuse_validated_baselines,
        ))
        candidate = get(build_candidate_task.chia_remote(
            paths["compiler_root"], paths["baseline_prefix"], paths["proposal"],
            args.jobs,
        ))
        candidate_id = candidate["candidate_id"][:12]
        candidate_manifest = str(
            Path(candidate["prefix"]) / "cost-model.json"
        )
        role3 = get(run_role_task.chia_remote(
            paths["repo"], paths["spec_dir"], candidate["prefix"],
            paths["baseline_prefix"], paths["speckle"], paths["qemu"],
            paths["out"], "3-saturn-aware", args.benchmark, args.size,
            candidate_id, candidate_manifest,
        ))
        summary = {
            "schema_version": 1,
            "workflow": "unchanged-SPEC roles 1-3",
            "target": {
                "config": TARGET_CONFIG,
                "firesim_config": TARGET_FIRESIM_CONFIG,
                "vlen": TARGET_VLEN,
                "dlen": TARGET_DLEN,
            },
            "roles": [role1, role2, role3],
            "candidate_manifest": candidate_manifest,
            "candidate_manifest_sha256": sha256(Path(candidate_manifest)),
            "performance_backend": None,
            "saturn_timing_complete": False,
            "result_scope": "SPEC/QEMU correctness and static code generation only",
        }
        destination = Path(paths["out"]) / f"{args.benchmark}-{args.size}-roles-1-3-chia.json"
        destination.write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary, sort_keys=True))
    finally:
        ray.shutdown()


if __name__ == "__main__":
    main()
