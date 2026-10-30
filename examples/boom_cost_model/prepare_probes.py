"""Prepare small pinned-compiler probes and validate them in QEMU, without FPGA work."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import sys

import ray
from ray import cloudpickle
from ray.util.scheduling_strategies import NodeAffinitySchedulingStrategy

from chia.base.ChiaFunction import ChiaFunction, get
from chia.chipyard.cost_model import BASELINE_GCC_SHA256, FLAGS, TARGET
from chia.chipyard.firemarshal_node import FireMarshalNode
from chia.chipyard.riscv_build_node import RiscvBuildNode
from chia.cluster.loopback import driver_options, require_guard
from examples.boom_cost_model.optimize import save
from examples.boom_cost_model.tasks import compiler_stage, qemu_stage

cloudpickle.register_pickle_by_value(sys.modules[__name__])
RECIPE_VERSION = "monotonic-clock-v2"


def probe_checksums() -> dict:
    """Compute independent expected unsigned-64 results without target execution."""
    mask = (1 << 64) - 1
    result = {}
    for operation in ("add", "multiply", "divide"):
        for chains in (1, 4):
            values = [17, 19, 23, 29]
            for index in range(chains):
                count = 400000 if chains == 1 else 100000
                if operation == "add":
                    values[index] = (values[index] + 31 * count) & mask
                elif operation == "multiply":
                    values[index] = values[index] * pow(3, count, 1 << 64) & mask
                else:
                    for _ in range(count):
                        value = (values[index] // 7 + 0xc000000000000001) & mask
                        if value == values[index]:
                            break
                        values[index] = value
            result[(operation, chains)] = values[0] ^ values[1] ^ values[2] ^ values[3]
    return result


def validate_probes(outputs: dict, success: bool, hardware: bool = False) -> list[dict]:
    """Require guest success and all six checksums, independently of timing."""
    statuses = [data.strip() for key, data in outputs.items() if key.endswith("/job.status")]
    records = [json.loads(line) for key, data in outputs.items() if key.endswith("/probes.jsonl")
               for line in data.splitlines()]
    expected = probe_checksums()
    if not success or statuses != [b"0"] or len(records) != 6 or \
            {(r["operation"], r["chains"]) for r in records} != expected.keys() or any(
                not r["correct"] or r["operations"] != 400000 or
                r["checksum"] != expected[(r["operation"], r["chains"])] or
                (hardware and (type(r["elapsed_ns"]) is not int or r["elapsed_ns"] <= 0)) for r in records):
        raise ValueError("probe completion, checksum or counter validation failed")
    return records


@ChiaFunction(resources={"firemarshal": 1}, max_retries=0)
def compose_probe(name, program, base):
    if not program.success or not base.success:
        raise RuntimeError("probe compilation or FireMarshal base failed")
    command = ('(mkdir -p /output; /root/probes/latency-probe > /output/probes.jsonl; '
               'rc=$?; echo "$rc" > /output/job.status; exit "$rc")')
    return FireMarshalNode().compose("br-base", program.files, name,
        config={"jobs": [{"name": "latency-probes", "command": command, "outputs": ["/output"]}]},
        overlay_modes=program.modes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
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
        affinity = {"scheduling_strategy": NodeAffinitySchedulingStrategy(nodes[0]["NodeID"], soft=False)}
        identity = get(compiler_stage.options(**affinity).chia_remote(config["gcc_root"], config["baseline_prefix"]))
        if identity["drivers"]["gcc"]["sha256"] != BASELINE_GCC_SHA256:
            raise ValueError("baseline compiler changed")
        source = Path(__file__).with_name("latency_probe.c").read_bytes()
        name = "boom-latency-probes-" + hashlib.sha256(
            source + BASELINE_GCC_SHA256.encode() + RECIPE_VERSION.encode()).hexdigest()[:12]
        cc = str(Path(config["baseline_prefix"]) / "bin" / (TARGET + "gcc"))
        command = "mkdir -p root/probes && " + shlex.join([cc, *FLAGS, "probe.c", "-o", "root/probes/latency-probe"])
        builder = RiscvBuildNode()
        program = builder.build_program.options(**affinity).chia_remote(builder,
            input_files={"probe.c": source}, command=["bash", "-c", command],
            work_dir="/tmp/spec_build", outputs=["root"])
        fm = FireMarshalNode()
        base = fm.build_base.options(resources={"firemarshal": 1}).chia_remote(fm, name="br-base")
        workload = get(compose_probe.chia_remote(name, program, base))
        compiled = get(program)
        (args.run_dir / "compiler.stdout").write_text(compiled.stdout)
        (args.run_dir / "compiler.stderr").write_text(compiled.stderr)
        if not workload.success:
            raise RuntimeError(workload.stderr)
        (args.run_dir / "workload.tar.gz").write_bytes(workload.archive)
        save(args.run_dir / "build.json", {"success": True, "descriptor": workload.json_name,
            "compiler": identity, "flags": FLAGS, "source_sha256": hashlib.sha256(source).hexdigest(),
            "archive_sha256": hashlib.sha256(workload.archive).hexdigest(),
            "recipe_version": RECIPE_VERSION,
            "FPGA_executed": False, "timing_interpretation": "QEMU timings are functional diagnostics only"})
        jobs = get(qemu_stage.chia_remote(workload.json_name, 900))
        if len(jobs) != 1:
            raise RuntimeError("expected exactly one probe job")
        job = jobs[0]
        (args.run_dir / "uart.log").write_bytes(job["uart"])
        for key, data in job["outputs"].items():
            path = Path(key)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("unsafe collected probe path")
            dest = args.run_dir / "collected" / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        try:
            records = validate_probes(job["outputs"], job["success"])
        except ValueError:
            save(args.run_dir / "correctness.json", {"success": False, "FPGA_executed": False})
            raise
        save(args.run_dir / "correctness.json", {"success": True, "records": records, "FPGA_executed": False})
        print("Probes built and QEMU correctness passed; no FPGA measurement performed.")
    finally:
        ray.shutdown()


if __name__ == "__main__":
    main()
