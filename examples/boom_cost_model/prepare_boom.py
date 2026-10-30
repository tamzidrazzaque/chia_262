"""Build a separate experimental -mtune=boom compiler in the existing worker."""

import argparse
import json
import os
from pathlib import Path

import ray
from ray.util.scheduling_strategies import NodeAffinitySchedulingStrategy

from chia.base.ChiaFunction import get
from chia.chipyard.boom_model import SEED_COSTS
from chia.cluster.loopback import driver_options, require_guard
from examples.boom_cost_model.optimize import save
from examples.boom_cost_model.tasks import compiler_stage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--costs-json", type=Path, help="Bounded scalar costs; defaults to source-seeded model")
    parser.add_argument("--issue-rate", type=int, default=4)
    parser.add_argument("--move-profile", type=Path, help="BOOM directional register and spill cost profile")
    args = parser.parse_args()
    os.umask(0o077)
    args.run_dir.mkdir(parents=True, exist_ok=True)
    config = json.loads(args.config.read_text())
    require_guard()
    ray.init(**driver_options(os.environ["RAY_ADDRESS"]))
    try:
        nodes = [n for n in ray.nodes() if n["Alive"] and n["Resources"].get("riscv_build")]
        if len(nodes) != 1:
            raise ValueError("expected one compiler worker")
        result = get(compiler_stage.options(scheduling_strategy=NodeAffinitySchedulingStrategy(
            nodes[0]["NodeID"], soft=False)).chia_remote(
                config["gcc_root"], config["baseline_prefix"],
                json.loads(args.costs_json.read_text()) if args.costs_json else SEED_COSTS,
                None if args.issue_rate == 4 else {"issue_rate": args.issue_rate}, "boom",
                json.loads(args.move_profile.read_text()) if args.move_profile else None))
        save(args.run_dir / "compiler.json", result)
        print(json.dumps({k: result[k] for k in ("compiler_id", "prefix", "tuning", "model_version")}, indent=2))
    finally:
        ray.shutdown()


if __name__ == "__main__":
    main()
