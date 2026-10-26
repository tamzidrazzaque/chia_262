"""Run the three fixed SPEC tuning configurations as real local CHIA tasks.

This validates RISC-V Linux binaries under QEMU and SPEC's correctness checks.
It does not produce BOOM cycles. The SPEC installation stays in a private path.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import ray

from chia.base.ChiaFunction import ChiaFunction, get

from spec_cpu2017_local import TUNES, validated


@ChiaFunction(num_cpus=1, max_retries=0)
def run_tune(spec_dir: str, gcc_root: str, speckle: str, qemu: str, out: str,
             tune: str, benchmark: str, size: str) -> dict:
    """Build and validate one tune on a worker with the private SPEC install."""
    script = Path(__file__).resolve().parent / "spec_cpu2017_local.py"
    common = [sys.executable, str(script), "--spec-dir", spec_dir, "--gcc-root", gcc_root,
              "--speckle", speckle, "--qemu", qemu, "--out", out, "--tune", tune,
              "--benchmark", benchmark, "--size", size]
    for action in ("build", "validate"):
        subprocess.run([*common, "--action", action], check=True, capture_output=True, text=True)
    log = Path(out) / f"{benchmark}-{size}-{tune}-validate.log"
    if not validated(log.read_text(), benchmark, size):
        raise RuntimeError(f"SPEC did not validate {benchmark} under {tune}; inspect {log}")
    metadata = json.loads((Path(out) / f"{benchmark}-{size}-{tune}-validate.json").read_text())
    return {"benchmark": benchmark, "size": size, "tune": tune, "validated": True,
            "gcc_version": metadata["gcc_version"], "gcc_sha256": metadata["gcc_sha256"],
            "config_sha256": metadata["config_sha256"], "log": str(log)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec-dir", type=Path, required=True)
    parser.add_argument("--gcc-root", type=Path, required=True)
    parser.add_argument("--speckle", type=Path, required=True)
    parser.add_argument("--qemu", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--benchmark", default="505.mcf_r")
    parser.add_argument("--size", choices=("test", "train", "ref"), default="test")
    parser.add_argument("--tunes", nargs="+", choices=TUNES, default=list(TUNES))
    parser.add_argument("--ray-temp", type=Path, default=Path("/tmp/ray-chia-spec"))
    args = parser.parse_args()
    if not re.fullmatch(r"[56]\d{2}\.[A-Za-z0-9_]+_[rs]", args.benchmark):
        parser.error("Expected a SPEC CPU2017 benchmark name")
    args.ray_temp.mkdir(mode=0o700, parents=True, exist_ok=True)
    ray.init(num_cpus=1, include_dashboard=False, _node_ip_address="127.0.0.1",
             _temp_dir=str(args.ray_temp.resolve()))
    try:
        results = []
        for tune in args.tunes:  # SPEC builds in its install, so serialize them.
            result = get(run_tune.chia_remote(
                str(args.spec_dir.resolve()), str(args.gcc_root.resolve()),
                str(args.speckle.resolve()), str(args.qemu.resolve()),
                str(args.out.resolve()), tune, args.benchmark, args.size))
            print(json.dumps(result, sort_keys=True))
            results.append(result)
        (args.out.resolve() / f"{args.benchmark}-{args.size}-chia-summary.json").write_text(
            json.dumps(results, indent=2) + "\n"
        )
    finally:
        ray.shutdown()


if __name__ == "__main__":
    main()
