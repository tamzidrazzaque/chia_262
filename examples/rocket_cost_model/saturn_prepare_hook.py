"""Prepare-hook implementation for :mod:`saturn_search_loop`.

All paths are supplied through environment variables so private SPEC trees and
toolchains remain outside Git.  The hook writes ``candidate-metadata.json``
for duplicate-ELF rejection before any hardware action.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from examples.rocket_cost_model.vector_cost_model import build_candidate


def required(name: str) -> Path:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"missing required environment variable {name}")
    return Path(value).resolve()


def main() -> None:
    work = required("SATURN_WORKDIR")
    proposal = json.loads(required("SATURN_PROPOSAL").read_text())
    proposal = {"changes": proposal["changes"], "rationale": proposal["rationale"]}
    candidate_id = os.environ["SATURN_CANDIDATE_ID"]
    repo = Path(os.environ.get("SATURN_REPO", Path(__file__).resolve().parents[2])).resolve()
    spec = required("SATURN_SPEC_DIR")
    baseline = required("SATURN_BASELINE_PREFIX")
    compiler_root = required("SATURN_COMPILER_ROOT") / candidate_id
    qemu = required("SATURN_QEMU")
    speckle = required("SATURN_SPECKLE")
    toolchain = required("SATURN_TOOLCHAIN")
    jobs = int(os.environ.get("SATURN_BUILD_JOBS", "8"))
    compiler = build_candidate(compiler_root, baseline, proposal, jobs)
    out = work / "spec"
    out.mkdir(mode=0o700)
    common = [sys.executable, str(repo / "examples/rocket_cost_model/spec_vector_baseline.py"),
              "--spec-dir", str(spec), "--gcc-root", str(compiler["prefix"]),
              "--speckle", str(speckle), "--qemu", str(qemu), "--out", str(out),
              "--role", "3-saturn-aware", "--benchmark", "605.mcf_s", "--size", "test",
              "--candidate-id", candidate_id[:32], "--candidate-manifest",
              str(Path(compiler["prefix"]) / "cost-model.json")]
    compiler_id = str(compiler["candidate_id"])[:32]
    for action in ("build", "validate"):
        common[common.index("--candidate-id") + 1] = compiler_id
        subprocess.run([*common, "--action", action], check=True)
    bundle = work / "bundle"
    subprocess.run([sys.executable, str(repo / "examples/rocket_cost_model/produce_spec_workload_bundle.py"),
                    "--spec-dir", str(spec), "--evidence", str(out), "--out", str(bundle),
                    "--toolchain", str(compiler["prefix"]), "--readelf",
                    str(toolchain / "bin/riscv64-unknown-linux-gnu-readelf"), "--objdump",
                    str(toolchain / "bin/riscv64-unknown-linux-gnu-objdump"), "--benchmark",
                    "605.mcf_s", "--size", "test", "--role", "3-saturn-aware",
                    "--candidate-id", compiler_id, "--candidate-manifest",
                    str(Path(compiler["prefix"]) / "cost-model.json")], check=True)
    elf_hash = hashlib.sha256((bundle / "payload/program").read_bytes()).hexdigest()
    (work / "candidate-metadata.json").write_text(json.dumps({
        "candidate_id": candidate_id, "executable_sha256": elf_hash,
        "bundle": str(bundle), "compiler_prefix": str(compiler["prefix"]),
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
