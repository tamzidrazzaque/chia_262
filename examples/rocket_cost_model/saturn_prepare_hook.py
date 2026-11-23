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
    compiler_root = required("SATURN_COMPILER_ROOT")
    if os.environ.get('SATURN_SHARED_COMPILER') != '1':
        compiler_root = compiler_root / candidate_id
    qemu = required("SATURN_QEMU")
    speckle = required("SATURN_SPECKLE")
    toolchain = required("SATURN_TOOLCHAIN")
    jobs = int(os.environ.get("SATURN_BUILD_JOBS", "8"))
    benchmark = os.environ.get('SATURN_BENCHMARK', '605.mcf_s')
    if benchmark not in ('605.mcf_s', '644.nab_s'):
        raise ValueError('unsupported admitted adaptive workload')
    # Fail before the expensive GCC build if the child bundle producer cannot
    # import the repository modules it needs.
    preflight_env = os.environ.copy()
    prior_path = preflight_env.get("PYTHONPATH")
    preflight_env["PYTHONPATH"] = str(repo) + ((os.pathsep + prior_path) if prior_path else "")
    subprocess.run(
        [sys.executable, "-c", "from examples.rocket_cost_model.spec_vector_baseline import role_settings"],
        check=True, env=preflight_env,
    )
    compiler = build_candidate(compiler_root, baseline, proposal, jobs)
    out = work / "spec"
    out.mkdir(mode=0o700)
    common = [sys.executable, str(repo / "examples/rocket_cost_model/spec_vector_baseline.py"),
              "--spec-dir", str(spec), "--gcc-root", str(compiler["prefix"]),
              "--speckle", str(speckle), "--qemu", str(qemu), "--out", str(out),
              "--role", "3-saturn-aware", "--benchmark", benchmark, "--size", "test",
              "--candidate-id", candidate_id[:32], "--candidate-manifest",
              str(Path(compiler["prefix"]) / "cost-model.json")]
    compiler_id = str(compiler["candidate_id"])[:32]
    for action in ("build", "validate"):
        common[common.index("--candidate-id") + 1] = compiler_id
        subprocess.run([*common, "--action", action], check=True)
    bundle = work / "bundle" / "3-saturn-aware"
    bundle_env = os.environ.copy()
    # The producer imports sibling modules; when invoked by absolute path the
    # repository root is not automatically placed on Python's import path.
    prior_path = bundle_env.get("PYTHONPATH")
    bundle_env["PYTHONPATH"] = str(repo) + ((os.pathsep + prior_path) if prior_path else "")
    subprocess.run([sys.executable, str(repo / "examples/rocket_cost_model/produce_spec_workload_bundle.py"),
                    "--spec-dir", str(spec), "--evidence", str(out), "--out", str(work / "bundle"),
                    "--toolchain", str(compiler["prefix"]), "--readelf",
                    str(toolchain / "bin/riscv64-unknown-linux-gnu-readelf"), "--objdump",
                    str(toolchain / "bin/riscv64-unknown-linux-gnu-objdump"), "--benchmark",
                    benchmark, "--size", "test", "--role", "3-saturn-aware",
                    "--candidate-id", compiler_id, "--candidate-manifest",
                    str(Path(compiler["prefix"]) / "cost-model.json")], check=True,
                   env=bundle_env)
    elf_hash = hashlib.sha256((bundle / "payload/program").read_bytes()).hexdigest()
    (work / "candidate-metadata.json").write_text(json.dumps({
        "candidate_id": candidate_id, "executable_sha256": elf_hash,
        "bundle": str(bundle), "compiler_prefix": str(compiler["prefix"]),
        "bundle_sha256": hashlib.sha256((bundle / 'manifest.json').read_bytes()).hexdigest(),
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
