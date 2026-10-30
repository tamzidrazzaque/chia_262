"""Validate prepared probes on each verified idle F2 before SPEC experiments."""

import argparse
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import subprocess
import traceback

import ray
from ray.util.scheduling_strategies import NodeAffinitySchedulingStrategy

from chia.base.ChiaFunction import get
from chia.chipyard.cost_model import BASELINE_GCC_SHA256, FLAGS
from chia.chipyard.state_def import FireMarshalArtifact
from chia.cluster.loopback import driver_options, require_guard
from examples.boom_cost_model.optimize import Experiment, save, verified_workers
from examples.boom_cost_model.prepare_probes import validate_probes, RECIPE_VERSION
from examples.boom_cost_model.tasks import fpga_stage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--probe-run-dir", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    args.run_dir.mkdir(parents=True, exist_ok=False)
    config = json.loads(args.config.read_text())
    metadata = json.loads((args.probe_run_dir / "build.json").read_text())
    archive = (args.probe_run_dir / "workload.tar.gz").read_bytes()
    source = Path(__file__).with_name("latency_probe.c").read_bytes()
    if (metadata.get("recipe_version") != RECIPE_VERSION or
            metadata["compiler"]["drivers"]["gcc"]["sha256"] != BASELINE_GCC_SHA256 or
            metadata["flags"] != FLAGS or metadata["source_sha256"] != hashlib.sha256(source).hexdigest() or
            metadata["archive_sha256"] != hashlib.sha256(archive).hexdigest() or
            not json.loads((args.probe_run_dir / "correctness.json").read_text())["success"]):
        raise ValueError("prepared probe identity or QEMU gate differs")
    require_guard()
    ray.init(**driver_options(os.environ["RAY_ADDRESS"]))
    try:
        experiment = Experiment(config, args.run_dir)
        workers = verified_workers(config, experiment.hardware)
        save(args.run_dir / "hardware-preflight.json", workers)
        job, = FireMarshalArtifact(archive=archive, json_name=metadata["descriptor"]).split()
        pending = {fpga_stage.options(scheduling_strategy=NodeAffinitySchedulingStrategy(
            w["node_id"], soft=False)).chia_remote(job, experiment.bitstream, experiment.run_config, 3600): w
            for w in workers}
        failures = []
        while pending:
            ready, _ = ray.wait(list(pending), num_returns=1)
            ref = ready[0]
            worker = pending.pop(ref)
            dest = args.run_dir / worker["instance_id"]
            dest.mkdir()
            try:
                result = get(ref)
                save(dest / "completion.json", {k: v for k, v in dataclasses.asdict(result).items()
                    if k not in ("outputs", "log", "uartlog")})
                (dest / "manager.log").write_text(result.log)
                (dest / "uart.log").write_text(result.uartlog)
                for key, data in result.outputs.items():
                    path = Path(key)
                    if path.is_absolute() or ".." in path.parts:
                        raise ValueError("unsafe collected output")
                    target = dest / "collected" / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                if result.node_id != worker["node_id"] or result.ip != worker["current_ip"]:
                    raise ValueError("probe result came from another worker")
                records = validate_probes(result.outputs, result.success, hardware=True)
                slot = subprocess.check_output(["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
                    worker["ssh_alias"], "sudo -n fpga-describe-local-image -S 0 -H"], text=True, timeout=30)
                (dest / "fpga-slot-after.log").write_text(slot)
                if experiment.hardware["AGFI"] not in slot.split() or "loaded" not in slot.split() or experiment.hardware["shell"] not in slot:
                    raise ValueError("probe measured a different FPGA image")
                save(dest / "correctness.json", {"success": True, "records": records, "FPGA_executed": True,
                     "interpretation": "Dependency/throughput comparisons include loop overhead; not SPEC scores"})
            except Exception as exc:
                failures.append(str(exc))
                save(dest / "failure.json", {"traceback": traceback.format_exc()})
        save(args.run_dir / "result.json", {"success": not failures, "failures": failures})
        if failures:
            raise RuntimeError("probe validation failed; see per-worker records")
    finally:
        ray.shutdown()


if __name__ == "__main__":
    main()
