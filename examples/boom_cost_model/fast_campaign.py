"""Batch compiler-sensitive kernels into one boot per F2; no SPEC data needed.

prepare is local compiler + FireMarshal + QEMU. measure uses existing approved
F2 workers. Reuse a prepared batch only with its exact source and artifact hashes.
"""

import argparse
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sys
import subprocess
import traceback

import ray
from ray import cloudpickle
from ray.util.scheduling_strategies import NodeAffinitySchedulingStrategy

from chia.base.ChiaFunction import ChiaFunction, get
from chia.chipyard import fast_screen
from chia.chipyard.cost_model import FLAGS, TARGET, BASELINE_GCC_SHA256, compiler_identity
from chia.chipyard.firemarshal_node import FireMarshalNode
from chia.chipyard.riscv_build_node import RiscvBuildNode
from chia.chipyard.state_def import FireMarshalArtifact
from chia.cluster.loopback import driver_options, require_guard
from examples.boom_cost_model.optimize import Experiment, save, verified_workers
from examples.boom_cost_model.tasks import compiler_stage, fpga_stage, qemu_stage

cloudpickle.register_pickle_by_value(sys.modules[__name__])
cloudpickle.register_pickle_by_value(fast_screen)
RECIPE = "fast-kernels-v1"


def executable_aliases(files, variants):
    """Deduplicate exact executable bytes before guest execution, keeping control first."""
    canonical, aliases = {}, {}
    for name in variants:
        digest = hashlib.sha256(files["root/fast/" + name]).hexdigest()
        aliases[name] = canonical.setdefault(digest, name)
    return aliases


def select_worker(config, requested):
    if requested is None:
        return config
    workers = [w for w in config.get("fpga_workers", [])
               if requested in (w["instance_id"], w["ssh_alias"])]
    if len(workers) != 1:
        raise ValueError("select exactly one worker already present in the approved config")
    return {**config, "fpga_workers": workers}


def store_outputs(directory, outputs):
    for name, data in outputs.items():
        path = Path(name)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("unsafe output path")
        dest = directory / "collected" / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)


def validate_outputs(outputs, success, variants, hardware=False, aliases=None):
    if not success or [v.strip() for k, v in outputs.items() if k.endswith("/job.status")] != [b"0"]:
        raise ValueError("batch guest or collection failed")
    results = {}
    for name in variants:
        canonical = (aliases or {}).get(name, name)
        records = [v for k, v in outputs.items() if k.endswith("/" + canonical + ".jsonl")]
        statuses = [v.strip() for k, v in outputs.items() if k.endswith("/" + canonical + ".status")]
        if len(records) != 1 or statuses != [b"0"]:
            raise ValueError("missing variant output/status")
        results[name] = fast_screen.validate_records(records[0], hardware)
        results[name].update(canonical_executable=canonical, independent_variant=name == canonical)
    return results


@ChiaFunction(resources={"firemarshal": 1}, max_retries=0)
def compose(name, program, base, variants):
    if not program.success or not base.success:
        raise RuntimeError("kernel compile or base build failed")
    commands = ["mkdir -p /output"]
    for variant in variants:
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", variant):
            raise ValueError("unsafe variant")
        commands.append(f"/root/fast/{variant} > /output/{variant}.jsonl; rc=$?; "
                        f"echo $rc > /output/{variant}.status; test $rc = 0 || exit $rc")
    commands.append("echo 0 > /output/job.status")
    files = {k: v for k, v in program.files.items() if k.startswith("root/")}
    return FireMarshalNode().compose("br-base", files, name,
        config={"jobs": [{"name": "fast-kernels", "command": "( " + "; ".join(commands) + " )",
                           "outputs": ["/output"]}]}, overlay_modes=program.modes)


@ChiaFunction(resources={"riscv_build": 1}, max_retries=0)
def verify_compilers(variants):
    for name, identity in variants.items():
        actual = compiler_identity(identity["prefix"])
        if name == "baseline" and actual["drivers"]["gcc"]["sha256"] != BASELINE_GCC_SHA256:
            raise ValueError("original compiler identity changed")
        if name != "baseline" and actual["manifest"]["compiler_id"] != identity["compiler_id"]:
            raise ValueError("candidate snapshot changed")
    return True


def prepare(args, config):
    nodes = [n for n in ray.nodes() if n["Alive"] and n["Resources"].get("riscv_build")]
    if len(nodes) != 1:
        raise ValueError("expected one compiler worker")
    affinity = {"scheduling_strategy": NodeAffinitySchedulingStrategy(nodes[0]["NodeID"], soft=False)}
    baseline = get(compiler_stage.options(**affinity).chia_remote(config["gcc_root"], config["baseline_prefix"]))
    variants = {"baseline": {"prefix": config["baseline_prefix"], "compiler_id": BASELINE_GCC_SHA256}}
    for filename in args.compiler:
        record = json.loads(filename.read_text())
        name = "candidate_" + record["compiler_id"][:12]
        variants[name] = record
    if len(variants) < 2:
        raise ValueError("provide at least one candidate compiler manifest")
    get(verify_compilers.options(**affinity).chia_remote(variants))
    source = Path(__file__).with_name("fast_kernels.c").read_bytes()
    commands = ["mkdir -p root/fast diagnostics"]
    for name, identity in variants.items():
        cc = str(Path(identity["prefix"]) / "bin" / (TARGET + "gcc"))
        commands.append(shlex.join([cc, *FLAGS, "kernels.c", "-o", "root/fast/" + name]))
        commands.append(shlex.join([cc, *FLAGS, "-S", "kernels.c", "-o", "diagnostics/" + name + ".s"]))
    commands.append("sha256sum root/fast/* > diagnostics/binaries.sha256")
    builder = RiscvBuildNode()
    program = builder.build_program.options(**affinity).chia_remote(builder,
        input_files={"kernels.c": source}, command=["bash", "-c", "set -e; " + "; ".join(commands)],
        work_dir="/tmp/spec_build", outputs=["root", "diagnostics"])
    fm = FireMarshalNode()
    base = fm.build_base.options(resources={"firemarshal": 1}).chia_remote(fm, name="br-base")
    compiled = get(program)
    (args.run_dir / "compiler.stdout").write_text(compiled.stdout)
    (args.run_dir / "compiler.stderr").write_text(compiled.stderr)
    # Only root/fast goes into the image; retain assembler diagnostics privately.
    for name, data in compiled.files.items():
        if name.startswith("diagnostics/"):
            dest = args.run_dir / name
            dest.parent.mkdir(exist_ok=True)
            dest.write_bytes(data)
    if not compiled.success:
        raise RuntimeError("kernel compilation failed; see compiler.stderr")
    aliases = executable_aliases(compiled.files, variants)
    selected = list(dict.fromkeys(aliases.values()))
    identity = hashlib.sha256(source + json.dumps([variants, aliases], sort_keys=True).encode() + RECIPE.encode()).hexdigest()
    workload = get(compose.chia_remote("boom-fast-" + identity[:12], program, base, selected))
    if not workload.success:
        raise RuntimeError(workload.stderr)
    (args.run_dir / "workload.tar.gz").write_bytes(workload.archive)
    save(args.run_dir / "build.json", {"recipe": RECIPE, "variants": variants, "aliases": aliases, "baseline": baseline,
         "source_sha256": hashlib.sha256(source).hexdigest(), "flags": FLAGS,
         "descriptor": workload.json_name, "archive_sha256": hashlib.sha256(workload.archive).hexdigest(),
         "FPGA_executed": False})
    jobs = get(qemu_stage.chia_remote(workload.json_name, 1800))
    if len(jobs) != 1:
        raise ValueError("expected one QEMU batch")
    job = jobs[0]
    (args.run_dir / "qemu-uart.log").write_bytes(job["uart"])
    store_outputs(args.run_dir / "qemu", job["outputs"])
    results = validate_outputs(job["outputs"], job["success"], variants, aliases=aliases)
    save(args.run_dir / "correctness.json", {"success": True, "FPGA_executed": False, "variants": results})
    print("Batched kernels prepared; independent checksums pass in QEMU. No hardware score yet.", flush=True)


def measure(args, config):
    metadata = json.loads((args.batch / "build.json").read_text())
    archive = (args.batch / "workload.tar.gz").read_bytes()
    if (metadata["recipe"] != RECIPE or metadata["flags"] != FLAGS or
            metadata["archive_sha256"] != hashlib.sha256(archive).hexdigest() or
            metadata["source_sha256"] != hashlib.sha256(Path(__file__).with_name("fast_kernels.c").read_bytes()).hexdigest() or
            not json.loads((args.batch / "correctness.json").read_text())["success"]):
        raise ValueError("batch identity/QEMU gate differs")
    experiment = Experiment(config, args.run_dir)
    workers = verified_workers(config, experiment.hardware)
    save(args.run_dir / "hardware-preflight.json", workers)
    job, = FireMarshalArtifact(archive=archive, json_name=metadata["descriptor"]).split()
    pending = {fpga_stage.options(scheduling_strategy=NodeAffinitySchedulingStrategy(
        w["node_id"], soft=False)).chia_remote(job, experiment.bitstream, experiment.run_config, 3600): w for w in workers}
    reports, failures = {}, []
    while pending:
        ready, _ = ray.wait(list(pending), num_returns=1)
        ref = ready[0]
        worker = pending.pop(ref)
        dest = args.run_dir / worker["instance_id"]
        dest.mkdir(exist_ok=True)
        try:
            result = get(ref)
            save(dest / "completion.json", {k: v for k, v in dataclasses.asdict(result).items()
                                             if k not in ("outputs", "log", "uartlog")})
            (dest / "manager.log").write_text(result.log)
            (dest / "uart.log").write_text(result.uartlog)
            store_outputs(dest, result.outputs)
            if result.node_id != worker["node_id"] or result.ip != worker["current_ip"]:
                raise ValueError("unexpected physical worker")
            slot = subprocess.check_output(["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
                worker["ssh_alias"], "sudo -n fpga-describe-local-image -S 0 -H"], text=True, timeout=30)
            (dest / "fpga-slot-after.log").write_text(slot)
            if experiment.hardware["AGFI"] not in slot.split() or "loaded" not in slot.split() or experiment.hardware["shell"] not in slot:
                raise ValueError("FPGA image or shell changed")
            data = validate_outputs(result.outputs, result.success, metadata["variants"], hardware=True,
                                    aliases=metadata.get("aliases"))
            scores = {name: fast_screen.geometric_speedup(data["baseline"]["median_ns"], report["median_ns"])
                      for name, report in data.items()}
            reports[worker["instance_id"]] = {"variants": data, "screening_speedups": scores}
            save(dest / "correctness.json", {"success": True, **reports[worker["instance_id"]]})
        except Exception as exc:
            failures.append(str(exc))
            save(dest / "failure.json", {"traceback": traceback.format_exc()})
    save(args.run_dir / "result.json", {"success": not failures, "reports": reports, "failures": failures,
        "batch": str(args.batch.resolve()), "interpretation": "Standalone kernel screen; SPEC transfer unvalidated"})
    if failures:
        raise RuntimeError("hardware screen failed; completed workers drained: " + "; ".join(failures))
    print(json.dumps({w: d["screening_speedups"] for w, d in reports.items()}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "measure"))
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--compiler", type=Path, action="append", default=[])
    parser.add_argument("--batch", type=Path)
    parser.add_argument("--worker", help="One configured instance ID or SSH alias; default validates both workers")
    args = parser.parse_args()
    if args.action == "measure" and args.batch is None:
        parser.error("measure requires --batch")
    os.umask(0o077)
    args.run_dir.mkdir(parents=True, exist_ok=False)
    config = select_worker(json.loads(args.config.read_text()), args.worker)
    require_guard()
    ray.init(**driver_options(os.environ["RAY_ADDRESS"]))
    try:
        (prepare if args.action == "prepare" else measure)(args, config)
    except Exception:
        save(args.run_dir / "failure.json", {"traceback": traceback.format_exc()})
        raise
    finally:
        ray.shutdown()


if __name__ == "__main__":
    main()
