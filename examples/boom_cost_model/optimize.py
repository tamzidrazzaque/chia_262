"""Bounded Claude CLI -> GCC cost table -> SPEC/QEMU -> existing MegaBOOM loop.

Run from the repository root with ``python -m examples.boom_cost_model.optimize``.
Licensed inputs and machine-specific configuration remain outside this example.
"""

from __future__ import annotations

import argparse
import dataclasses
import fcntl
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
import traceback
from types import SimpleNamespace

import ray
from ray.util.scheduling_strategies import NodeAffinitySchedulingStrategy

from chia.base.ChiaFunction import get
from chia.chipyard.cost_model import BASE_COSTS, BASELINE_GCC_SHA256, validate_costs, validate_scheduling
from chia.chipyard.measurements import measurement_key, validated_cache, prior_train_evidence
from chia.chipyard.spec_validation import completion_status, real_time, relative_speedup
from chia.cluster.loopback import driver_options, require_guard
from chia.firesim.fs_bitstream import FSBitstream
from chia.firesim.state_def import RunConfig
from chia.models.claude import ClaudeCodeLLM
from examples.boom_cost_model.tasks import (compiler_stage, validate_stage, qemu_stage, fpga_stage,
                                          build_diagnostics, workload_fingerprints, fpga_worker_identity)
from examples.spec_build.spec_sw_build_loop import start_workload

ROOT = Path(__file__).resolve().parents[2]
BOOM_CHARACTERIZATION = {
    "boom_revision": "5223e44cfeb26f41380057a2eb4d651197475f69",
    "decode_width": 4, "integer_issue_queue_width": 4, "default_integer_multiply_latency": 3,
    "source": "https://github.com/riscv-boom/riscv-boom/blob/5223e44cfeb26f41380057a2eb4d651197475f69/src/main/scala/v3/common/config-mixins.scala",
    "parameter_source": "https://github.com/riscv-boom/riscv-boom/blob/5223e44cfeb26f41380057a2eb4d651197475f69/src/main/scala/v3/common/parameters.scala",
    "interpretation": "Pinned configuration facts, not measured instruction throughput. "
                      "GCC generic multiply scheduling latency is10 and issue_rate is1. "
                      "Cost estimates and pipeline scheduling reservations are distinct.",
}


class CandidateRejected(ValueError):
    """A candidate failed a bounded proposal or benchmark correctness gate."""


def save(path: Path, value) -> None:
    """Atomically record metadata so interrupted runs can resume."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def resumed_proposal(directory: Path, index: int, prompt: dict) -> str | None:
    """Reuse a validated proposal after an infrastructure failure on the FPGA."""
    prompt_path = directory / "claude" / f"prompt-{index:03d}.json"
    response_path = directory / "claude" / f"response-{index:03d}.txt"
    compiler_path = directory / f"candidate-{index:03d}" / "compiler.json"
    if not (response_path.exists() and compiler_path.exists()):
        return None
    if not prompt_path.exists() or json.loads(prompt_path.read_text()) != prompt:
        raise ValueError("saved proposal prompt differs from the current run")
    response = response_path.read_text()
    if not response.strip():
        raise ValueError("saved proposal response is empty")
    return response


def proposal(text: str, scheduling: bool = False) -> dict:
    """Parse a tool-free JSON proposal; executable patches are never accepted."""
    text = text.strip()
    if text.startswith("```json\n") and text.endswith("\n```"):
        text = text[8:-4]
    result = json.loads(text)
    fields = {"costs", "rationale", "scheduling"} if scheduling else {"costs", "rationale"}
    if not isinstance(result, dict) or result.keys() != fields:
        raise ValueError("Claude must return costs and rationale only")
    validate_costs(result["costs"])
    if scheduling:
        validate_scheduling(result["scheduling"])
        if result["costs"] != BASE_COSTS:
            raise ValueError("issue-rate experiment must hold optimization costs fixed")
    if not isinstance(result["rationale"], str) or len(result["rationale"]) > 8000:
        raise ValueError("invalid proposal rationale")
    return result


def aws(config: dict, *args) -> dict:
    """Read AWS metadata through the user's login profile, never access keys."""
    command = ["aws", "--profile", config["aws_profile"], "--region", config["region"],
               *args, "--output", "json", "--no-cli-pager"]
    for attempt in range(3):
        try:
            return json.loads(subprocess.check_output(command, text=True, stderr=subprocess.PIPE))
        except subprocess.CalledProcessError as exc:
            # Retry transient transport failures; authentication/policy errors
            # still fail promptly and never weaken hardware/network checks.
            if attempt == 2 or "Could not connect to the endpoint URL" not in (exc.stderr or ""):
                sys.stderr.write(exc.stderr or "")
                raise
            time.sleep(1 + attempt)


def hardware_preflight(config: dict, hardware: dict) -> dict:
    """Verify current instance/IP, approved network policy and matching image."""
    identity = aws(config, "sts", "get-caller-identity")
    if identity["Arn"] != f"arn:aws:iam::{config['aws_account']}:user/{config['iam_user']}":
        raise ValueError("AWS identity differs from the experiment IAM user")
    response = aws(config, "ec2", "describe-instances", "--instance-ids", config["instance_id"])
    instance = response["Reservations"][0]["Instances"][0]
    if instance["State"]["Name"] != "running" or not instance["InstanceType"].startswith("f2."):
        raise ValueError("the existing F2 must be running")
    ip = instance["PublicIpAddress"]
    if {g["GroupId"] for g in instance["SecurityGroups"]} - set(config["security_group_ids"]):
        raise ValueError("F2 has a security group outside the approved policy")
    groups = aws(config, "ec2", "describe-security-groups", "--group-ids", *config["security_group_ids"])
    policy = {g["GroupId"]: {k: g[k] for k in ("IpPermissions", "IpPermissionsEgress")}
              for g in groups["SecurityGroups"]}
    normalize = lambda obj: json.dumps(obj, sort_keys=True)
    if normalize(policy) != normalize(config["approved_network_policy"]):
        raise ValueError("AWS network policy differs from approved lab restrictions")
    image = aws(config, "ec2", "describe-fpga-images", "--filters",
                "Name=fpga-image-global-id,Values=" + hardware["AGFI"])["FpgaImages"]
    if len(image) != 1 or image[0]["State"]["Code"] != "available" or image[0]["FpgaImageId"] != hardware["AFI"]:
        raise ValueError("matching FPGA image is not available")
    effective = subprocess.check_output(["ssh", "-G", config["ssh_alias"]], text=True, stderr=subprocess.DEVNULL)
    if f"hostname {ip}\n" not in effective:
        raise ValueError(f"F2 IP is now {ip}; update the owned SSH alias and Chia worker tunnels first")
    proc = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
                           "-o", "ConnectTimeout=15", config["ssh_alias"],
                           "set -e; sudo -n /usr/sbin/sshd -T | sed -n '/^gatewayports /p'; "
                           "sudo -n fpga-describe-local-image -S 0 -H"],
                          capture_output=True, text=True, timeout=30, check=True)
    if "gatewayports no" not in proc.stdout:
        raise ValueError("F2 must retain GatewayPorts=no")
    if hardware["shell"] not in proc.stdout:
        raise ValueError("F2 shell differs from the verified matching hardware")
    return {"identity": identity, "instance_id": config["instance_id"], "current_ip": ip,
            "instance_type": instance["InstanceType"], "network_policy": policy,
            "image": image[0], "slot_before_run": proc.stdout}


def verified_workers(config: dict, hardware: dict) -> list[dict]:
    """Verify each explicitly configured instance and bind it to its Ray node."""
    requested = config.get("fpga_workers", [{k: config[k] for k in ("instance_id", "ssh_alias")}])
    if not requested or len({w["instance_id"] for w in requested}) != len(requested):
        raise ValueError("FPGA workers must be nonempty and distinct")
    nodes = [n for n in ray.nodes() if n["Alive"] and n["Resources"].get("firesim_fpga")]
    result = []
    for worker in requested:
        report = hardware_preflight({**config, **worker}, hardware)
        active = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "ConnectTimeout=15", worker["ssh_alias"], "pgrep -x FireSim-f2"],
            capture_output=True, text=True, timeout=30)
        if active.returncode == 0:
            raise RuntimeError(f"{worker['ssh_alias']} has an active FireSim driver; preserve it before retrying")
        if active.returncode != 1:
            raise RuntimeError("could not verify the FPGA slot is idle")
        matches = [n for n in nodes if not worker.get("ray_address") or
                   n["NodeManagerAddress"] == worker["ray_address"]]
        if len(matches) != 1:
            raise ValueError("configure a unique ray_address for each FPGA worker")
        node = matches[0]
        identity = get(fpga_worker_identity.options(scheduling_strategy=
            NodeAffinitySchedulingStrategy(node["NodeID"], soft=False)).chia_remote())
        if identity["node_id"] != node["NodeID"] or identity["ip"] != report["current_ip"]:
            raise RuntimeError("SSH instance and Ray worker identity differ")
        result.append({**worker, **report, "node_id": node["NodeID"]})
    return result


class Experiment:
    """Serial experiment controller; only measured, correct candidates can win."""

    def __init__(self, config: dict, directory: Path):
        self.config, self.directory = config, directory
        nodes = [n for n in ray.nodes() if n["Alive"] and n["Resources"].get("riscv_build")]
        if len(nodes) != 1:
            raise ValueError("expected one compiler worker in this private cluster")
        self.compiler_node = nodes[0]["NodeID"]
        self.affinity = {"scheduling_strategy": NodeAffinitySchedulingStrategy(self.compiler_node, soft=False)}
        if not any(n["Alive"] and n["Resources"].get("firemarshal") for n in ray.nodes()):
            raise ValueError("FireMarshal worker unavailable")
        self.hardware = json.loads(Path(config["hardware_manifest"]).read_text())
        hw = self.hardware
        if not hw["matching_source_verified"] or "MegaBoom" not in hw["quintuplet"] or \
                hw["AGFI"] != "agfi-0f4582f3f39b9a8a4" or hw["shell"] != "0x10212415" or \
                hw["Chipyard_revision"] != "19a07f6b8d4d1db81f5561d9aeceb2cdc43407fe" or \
                hw["FireSim_revision"] != "b7927ea504c501194eaec3e993c415f2270170f8":
            raise ValueError("this experiment requires the verified public FRFCFS/LLC MegaBOOM image")
        driver = Path(hw["driver_bundle"]).read_bytes()
        if hashlib.sha256(driver).hexdigest() != hw["driver_bundle_sha256"]:
            raise ValueError("matching driver bundle hash changed")
        self.bitstream = FSBitstream(hw["quintuplet"], agfi=hw["AGFI"], driver_bytes=driver)
        self.run_config = RunConfig.from_yaml(str(ROOT / "examples/firesim_spec/config_runtime.yaml"))
        if (directory / "hardware.json").exists() and json.loads((directory / "hardware.json").read_text()) != self.hardware:
            raise ValueError("hardware manifest changed; use a new experiment directory")
        save(directory / "hardware.json", self.hardware)
        runtime = (ROOT / "examples/firesim_spec/config_runtime.yaml").read_bytes()
        if (directory / "config_runtime.yaml").exists() and (directory / "config_runtime.yaml").read_bytes() != runtime:
            raise ValueError("runtime configuration changed; use a new experiment directory")
        (directory / "config_runtime.yaml").write_bytes(runtime)

    def compiler(self, costs=None, scheduling=None) -> dict:
        """Inspect/rebuild exclusively on the selected compiler worker."""
        return get(compiler_stage.options(**self.affinity).chia_remote(
            self.config["gcc_root"], self.config["baseline_prefix"], costs, scheduling))

    def workload(self, identity: dict, inputs: str, directory: Path):
        """Build through the pinned Speckle/FireMarshal stages and save evidence."""
        directory.mkdir(parents=True, exist_ok=True)
        workload = get(start_workload("spec17-intspeed-" + inputs, cores=1, spec_flags="",
                                     small_images=self.config.get("small_images", False),
                                     benchmarks=self.config["benchmarks"],
                                     compiler_id=identity["compiler_id"],
                                     compiler_prefix=identity["prefix"], compiler_node_id=self.compiler_node))
        save(directory / "build.json", {"spec": "spec17-intspeed-" + inputs,
             "compiler": identity, "success": workload.success, "descriptor": workload.json_name,
             "returncode": workload.returncode, "benchmarks": self.config["benchmarks"],
             "cores": 1, "spec_flags": "", "FPGA_executed": False})
        (directory / "build.stdout").write_text(workload.stdout)
        (directory / "build.stderr").write_text(workload.stderr)
        if workload.json_name:
            logs = get(build_diagnostics.chia_remote(workload.json_name))
            for name, data in logs.items():
                path = Path(name)
                if path.is_absolute() or ".." in path.parts:
                    raise ValueError("unsafe compiler diagnostic path")
                dest = directory / "build-logs" / path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
        if not workload.success:
            raise RuntimeError(f"SPEC/image build failed; see {directory}")
        (directory / "workload.tar.gz").write_bytes(workload.archive)
        return workload

    def collect(self, outputs: dict, directory: Path, inputs: str, success: bool) -> float:
        """Save raw outputs before validation; refuse failed/incorrect results."""
        directory.mkdir(parents=True, exist_ok=True)
        for name, data in outputs.items():
            path = Path(name)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("unsafe result path")
            dest = directory / "collected" / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        if not success:
            raise RuntimeError(f"simulation failed; see {directory}")
        try:
            completion_status(outputs)
        except ValueError as exc:
            raise CandidateRejected(str(exc)) from exc
        result = get(validate_stage.options(**self.affinity).chia_remote(outputs, inputs))
        save(directory / "correctness.json", result)
        if not result["success"]:
            raise CandidateRejected(f"SPEC output comparison failed; see {directory}")
        return real_time(outputs)

    def evaluate(self, identity: dict, inputs: str, label: str, qemu: bool = False) -> dict:
        """Run all selected jobs, validate outputs, and persist measured timings."""
        directory = self.directory / label / inputs
        actual = get(compiler_stage.options(**self.affinity).chia_remote(
            self.config["gcc_root"], identity["prefix"]))
        if identity["prefix"] == self.config["baseline_prefix"]:
            if actual["drivers"]["gcc"]["sha256"] != BASELINE_GCC_SHA256:
                raise ValueError("original baseline changed")
        elif not actual["manifest"] or actual["manifest"]["compiler_id"] != identity["compiler_id"]:
            raise ValueError("candidate prefix and identity differ")
        report = directory / "evaluation.json"
        if report.exists():
            cached = json.loads(report.read_text())
            if cached["compiler"] == identity and cached["inputs"] == inputs and cached["success"]:
                return cached
        workload = self.workload(identity, inputs, directory)
        repetitions = 1 if qemu else self.config["repeats"]
        timings = {}
        for repeat in range(repetitions):
            if qemu:
                jobs = get(qemu_stage.chia_remote(workload.json_name,
                    self.config.get("qemu_timeout_seconds", 900), self.config.get("qemu_memory_mb", 2048)))
                for job in jobs:
                    dest = directory / str(repeat) / job["name"]
                    dest.mkdir(parents=True, exist_ok=True)
                    (dest / "uart.log").write_bytes(job["uart"])
                    save(dest / "completion.json", {k: v for k, v in job.items() if k not in ("uart", "outputs")})
                    self.collect(job["outputs"], dest, inputs, job["success"])
                if len(jobs) != len(self.config["benchmarks"]):
                    raise RuntimeError("QEMU did not complete every selected benchmark")
            else:
                self.measure_jobs(workload, directory / str(repeat), inputs, repeat, timings)
        if not qemu and (timings.keys() != set(self.config["benchmarks"]) or
                         any(len(v) != repetitions for v in timings.values())):
            raise RuntimeError("incomplete timing set")
        result = {"success": True, "compiler": identity, "inputs": inputs,
                  "FPGA_executed": not qemu, "raw_times": timings,
                  "times": {k: statistics.median(v) for k, v in timings.items()}}
        result["timing_spread"] = {k: {"min": min(v), "max": max(v),
            "relative_range": (max(v) - min(v)) / statistics.median(v),
            "repeat_count": len(v)} for k, v in timings.items()}
        fingerprint_path = directory / "workload-fingerprints.json"
        if not qemu and fingerprint_path.exists():
            fingerprints = json.loads(fingerprint_path.read_text())
            result["code_generation"] = {b: next(v.get("executables", {}) for k, v in fingerprints.items()
                if k.endswith(b)) for b in self.config["benchmarks"]}
        save(report, result)
        return result

    def measure_jobs(self, workload, directory: Path, inputs: str, repeat: int, timings: dict) -> None:
        """Dispatch to vetted workers concurrently; reuse only identical validated samples."""
        workers = getattr(self, "workers", [])
        if not workers:
            raise RuntimeError("no verified, idle FPGA workers; preserve any active reference run")
        fingerprints = get(workload_fingerprints.chia_remote(workload.json_name))
        save(directory.parent / "workload-fingerprints.json", fingerprints)
        runtime_hash = hashlib.sha256((self.directory / "config_runtime.yaml").read_bytes()).hexdigest()
        pending = list(enumerate(workload.split()))
        running = {}
        cache = self.directory / "measurement-cache"
        timeout = self.config.get("ref_timeout_seconds" if inputs == "ref" else "train_timeout_seconds",
                                  72 * 3600 if inputs == "ref" else 24 * 3600)

        def submit(index, job, worker):
            name = Path(job.json_name).stem
            fingerprint = fingerprints[name]
            key = measurement_key(fingerprint, self.hardware, runtime_hash, worker["instance_id"], inputs, repeat)
            dest = directory / name
            cached = validated_cache(cache, key)
            if cached:
                record, outputs = cached
                value = self.collect(outputs, dest, inputs, True)
                save(dest / "measurement.json", {"key": key, "reused": True, "source": record["source"],
                     "independent_measurement": False, "instance_id": worker["instance_id"]})
                benchmark = next(b for b in self.config["benchmarks"] if name.endswith(b))
                timings.setdefault(benchmark, []).append(value)
                return False
            strategy = NodeAffinitySchedulingStrategy(worker["node_id"], soft=False)
            ref = fpga_stage.options(scheduling_strategy=strategy).chia_remote(
                job, self.bitstream, self.run_config, timeout)
            running[ref] = (worker, dest, key, fingerprint)
            return True

        # Fixed round-robin pairing keeps each benchmark on the same physical
        # worker across compilers. Repeat indices remain independent cache keys.
        queues = {w["instance_id"]: [] for w in workers}
        for index, job in pending:
            queues[workers[index % len(workers)]["instance_id"]].append((index, job))

        def next_job(worker):
            queue = queues[worker["instance_id"]]
            while queue:
                index, job = queue.pop(0)
                if submit(index, job, worker):
                    break

        for worker in workers:
            next_job(worker)
        failures = []
        while running:
            ready, _ = ray.wait(list(running), num_returns=1)
            ref = ready[0]
            worker, dest, key, fingerprint = running.pop(ref)
            try:
                result = get(ref)
                if result.node_id != worker["node_id"] or result.ip != worker["current_ip"]:
                    raise RuntimeError("FPGA result came from another worker")
                dest.mkdir(parents=True, exist_ok=True)
                (dest / "manager.log").write_text(result.log)
                (dest / "uart.log").write_text(result.uartlog)
                save(dest / "completion.json", {k: v for k, v in dataclasses.asdict(result).items()
                                                if k not in ("outputs", "log", "uartlog")})
                value = self.collect(result.outputs, dest, inputs, result.success)
                slot = subprocess.check_output(["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
                    "-o", "ConnectTimeout=15", worker["ssh_alias"],
                    "sudo -n fpga-describe-local-image -S 0 -H"], text=True, timeout=30)
                (dest / "fpga-slot-after.log").write_text(slot)
                if self.hardware["AGFI"] not in slot.split() or "loaded" not in slot.split() or self.hardware["shell"] not in slot:
                    raise RuntimeError("loaded AGFI/shell differs from the measured target")
                save(dest / "measurement.json", {"key": key, "fingerprint": fingerprint, "reused": False,
                     "independent_measurement": True, "instance_id": worker["instance_id"]})
                save(cache / (key + ".json"), {"key": key, "source": str(dest.resolve()), "real_time": value,
                     "output_hashes": {k: hashlib.sha256(v).hexdigest() for k, v in result.outputs.items()}})
                benchmark = next(b for b in self.config["benchmarks"] if result.benchmark_name.endswith(b))
                timings.setdefault(benchmark, []).append(value)
            except Exception as exc:
                failures.append(str(exc))
                save(dest / "failure.json", {"traceback": traceback.format_exc()})
            if not failures:
                next_job(worker)
        if failures:
            raise RuntimeError("FPGA evaluation failed; active jobs were drained and saved: " + "; ".join(failures))


def run(config: dict, directory: Path, prepare_only: bool) -> None:
    """Run/resume bounded proposals, correctness gates and final held-out checks."""
    experiment = Experiment(config, directory)
    if not prepare_only:
        experiment.workers = verified_workers(config, experiment.hardware)
        save(directory / "hardware-preflight.json", experiment.workers)
        if not any(n["Alive"] and n["Resources"].get("firesim_fpga") for n in ray.nodes()):
            raise ValueError("existing F2 worker/tunnels need reconnecting")
    identity = experiment.compiler()
    if identity["drivers"]["gcc"]["sha256"] != BASELINE_GCC_SHA256:
        raise ValueError("baseline compiler changed")
    baseline = {"compiler_id": BASELINE_GCC_SHA256, "prefix": config["baseline_prefix"]}
    save(directory / "baseline-identity.json", identity)
    print("Checking unmodified GCC rebuild", flush=True)
    rebuilt = experiment.compiler(BASE_COSTS)
    save(directory / "unmodified-rebuild.json", rebuilt)
    experiment.evaluate(baseline, "test", "baseline-qemu", qemu=True)
    rebuilt_identity = {"compiler_id": rebuilt["compiler_id"], "prefix": rebuilt["prefix"]}
    experiment.evaluate(rebuilt_identity, "test", "unmodified-qemu", qemu=True)
    if prepare_only:
        print("Compiler rebuild and baseline/rebuilt QEMU correctness gates passed.", flush=True)
        return
    print("Measuring original baseline on MegaBOOM F2 (train inputs)", flush=True)
    baseline_result = experiment.evaluate(baseline, "train", "baseline-f2")
    history, best, best_score = [], baseline, 1.0
    scheduling_search = config.get("search_mode", "costs") == "issue-rate"
    previous = prior_train_evidence(config.get("prior_runs", []), experiment.hardware)
    save(directory / "prior-train-evidence.json", previous)
    # Use CLI authentication and no model shell/filesystem tools. The controller
    # owns all mutations, compile flags, evaluator logic and hardware settings.
    os.environ.pop("ANTHROPIC_API_KEY", None)
    llm = ClaudeCodeLLM(backend="cli", model=config["model"], resume_session=True,
                        projects_cwd=None, dangerously_skip_permissions=False,
                        extra_cli_args=["--tools", "", "--strict-mcp-config"], retries=1,
                        log_dir=str(directory / "claude"), timeout_seconds=600,
                        system_message="Propose bounded GCC cost-table values as JSON only. Do not use tools.")
    for index in range(config["iterations"]):
        record_path = directory / f"candidate-{index:03d}.json"
        if record_path.exists():
            record = json.loads(record_path.read_text())
        else:
            print(f"Claude proposal {index + 1}/{config['iterations']}", flush=True)
            prompt = {"goal": "Improve SPEC2017 intspeed runtime on the fixed MegaBOOM F2 target",
                      "hardware": {k: experiment.hardware[k] for k in ("AGFI", "quintuplet", "frequency_MHz")},
                      "hardware_characterization": BOOM_CHARACTERIZATION,
                      "constraints": "GCC revision, baseline flags, ISA, ABI and inputs fixed. "
                                     "Only rocket_tune_info cost fields may change. All costs integers 1..64. "
                                     "Paired arrays are single/double or 32/64-bit costs in COSTS_N_INSNS units. "
                                     "No issue_rate or slow_unaligned_access changes. "
                                     "Only test correctness and train timings may guide proposals; ref held out.",
                      "baseline_costs": BASE_COSTS, "baseline_train_times": baseline_result["times"],
                      "history": history, "prior_train_evidence": previous,
                      "response_format": {"costs": BASE_COSTS, "rationale": "brief explanation"}}
            if scheduling_search:
                prompt["constraints"] = ("Separate issue-rate experiment: keep all optimization costs at baseline. "
                    "Only rocket_tune_info issue_rate may change to an integer 1..8. Generic pipeline reservations "
                    "and latencies remain fixed; changing issue_rate alone does not make a complete BOOM scheduler. "
                    "Compiler revision, flags, ISA/ABI and inputs fixed. Reference results are held out.")
                prompt["response_format"]["scheduling"] = {"issue_rate": 1}
            seeds = config.get("seed_proposals", [])
            previous_response = resumed_proposal(directory, index, prompt)
            if previous_response is not None:
                print(f"Reusing saved proposal {index + 1}/{config['iterations']}", flush=True)
                response = SimpleNamespace(success=True, result=previous_response)
            else:
                save(directory / "claude" / f"prompt-{index:03d}.json", prompt)
                response = (SimpleNamespace(success=True, result=json.dumps(seeds[index]))
                            if index < len(seeds) else llm.prompt(json.dumps(prompt), tools=[]))
                (directory / "claude" / f"response-{index:03d}.txt").write_text(response.result)
                (directory / "claude" / f"response-{index:03d}.stderr").write_text(getattr(response, "stderr", "") or "")
            if not response.success:
                raise RuntimeError("Claude CLI failed; see private controller logs")
            try:
                try:
                    suggested = proposal(response.result, scheduling_search)
                except (ValueError, TypeError) as exc:
                    raise CandidateRejected(str(exc)) from exc
                record = {"index": index, "proposal": suggested, "success": False,
                          "proposal_source": "seed" if index < len(seeds) else "claude-cli"}
                costs = suggested["costs"]
                scheduling = suggested.get("scheduling")
                if (costs == BASE_COSTS and scheduling in (None, {"issue_rate": 1})) or any(
                        h.get("proposal", {}).get("costs") == costs and
                        h.get("proposal", {}).get("scheduling") == scheduling for h in history):
                    raise CandidateRejected("proposal repeats an already tested cost table")
                compiled = experiment.compiler(costs, scheduling) if scheduling else experiment.compiler(costs)
                compiler_path = directory / f"candidate-{index:03d}" / "compiler.json"
                if (compiler_path.exists() and
                        json.loads(compiler_path.read_text())["compiler_id"] != compiled["compiler_id"]):
                    raise ValueError("resumed compiler differs from the saved candidate")
                save(compiler_path, compiled)
                selected = {"compiler_id": compiled["compiler_id"], "prefix": compiled["prefix"]}
                experiment.evaluate(selected, "test", f"candidate-{index:03d}-qemu", qemu=True)
                measured = experiment.evaluate(selected, "train", f"candidate-{index:03d}-f2")
                score = relative_speedup(baseline_result["times"], measured["times"])
                record.update(success=True, compiler=selected, train_times=measured["times"], speedup=score)
                record["train_timing_spread"] = measured.get("timing_spread", {})
                record["codegen_identical_to_baseline"] = {
                    b: (measured["code_generation"][b] == baseline_result["code_generation"][b]
                        if measured.get("code_generation", {}).get(b) and
                        baseline_result.get("code_generation", {}).get(b) else None)
                    for b in config["benchmarks"]}
            except CandidateRejected as exc:
                # Compiler/proposal/correctness failures become feedback, never
                # a fabricated score. Infrastructure/auth failures stop the run.
                if "record" not in locals() or record.get("index") != index:
                    record = {"index": index, "success": False}
                record["failure"] = str(exc)
                save(record_path.with_suffix(".failure.json"), {"traceback": traceback.format_exc()})
            save(record_path, record)
        history.append(record)
        if record.get("success") and record["speedup"] > best_score * (1 + config["min_improvement"]):
            best, best_score = record["compiler"], record["speedup"]
        save(directory / "progress.json", {"best": best, "train_speedup": best_score, "history": history})
    final = {"complete": True, "hardware": experiment.hardware, "benchmarks": config["benchmarks"],
             "best": best, "train_speedup": best_score, "repeats": config["repeats"],
             "full_suite": False, "SPEC_reportable_score": False, "reference_checked": False}
    if config["final_ref"]:
        base_ref = experiment.evaluate(baseline, "ref", "baseline-heldout")
        winner_ref = base_ref if best == baseline else experiment.evaluate(best, "ref", "winner-heldout")
        final.update(reference_checked=True, reference_speedup=relative_speedup(base_ref["times"], winner_ref["times"]))
    save(directory / "result.json", final)
    print(json.dumps(final, indent=2), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True, help="Private output directory; rerun to resume")
    parser.add_argument("--prepare-only", action="store_true", help="Rebuild/QEMU gates without AWS, Claude or FPGA runs")
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    allowed = {"600.perlbench_s", "602.gcc_s", "605.mcf_s", "623.xalancbmk_s", "625.x264_s",
               "631.deepsjeng_s", "641.leela_s", "648.exchange2_s"}
    if not isinstance(config["benchmarks"], list) or not config["benchmarks"] or \
            len(set(config["benchmarks"])) != len(config["benchmarks"]) or set(config["benchmarks"]) - allowed:
        parser.error("select distinct supported single-job SPEC2017 intspeed benchmarks; OMNeT++/multi-job XZ remain excluded")
    if config.get("search_mode", "costs") not in ("costs", "issue-rate"):
        parser.error("search_mode must be costs or issue-rate")
    for field, default in (("train_timeout_seconds", 86400), ("ref_timeout_seconds", 259200),
                           ("qemu_timeout_seconds", 900)):
        val = config.get(field, default)
        if type(val) is not int or not 60 <= val <= 604800:
            parser.error(f"{field} must be an integer from 60 to 604800 seconds")
    memory = config.get("qemu_memory_mb", 2048)
    if type(memory) is not int or not 2048 <= memory <= 12288:
        parser.error("qemu_memory_mb must be an integer from 2048 to 12288")
    for seed in config.get("seed_proposals", []):
        proposal(json.dumps(seed), config.get("search_mode") == "issue-rate")
    if type(config["iterations"]) is not int or not 1 <= config["iterations"] <= 20 or \
            type(config["repeats"]) is not int or not 1 <= config["repeats"] <= 5 or \
            not 0 <= config["min_improvement"] <= 0.1 or type(config["final_ref"]) is not bool:
        parser.error("invalid iteration/repetition/selection bounds")
    os.umask(0o077)
    args.run_dir.mkdir(parents=True, exist_ok=True)
    with (args.run_dir / "controller.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error("this run already has an active controller")
        snapshot = args.run_dir / "config.json"
        if snapshot.exists() and json.loads(snapshot.read_text()) != config:
            parser.error("configuration changed; use a new run directory")
        save(snapshot, config)
        invocation = {"command": sys.argv, "time": time.time(),
             "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
             "source_hashes": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in [Path(__file__), ROOT / "examples/boom_cost_model/tasks.py",
                                         ROOT / "chia/chipyard/cost_model.py", ROOT / "chia/chipyard/spec_validation.py",
                                         ROOT / "chia/chipyard/measurements.py", ROOT / "chia/firesim/manager_node.py",
                                         ROOT / "examples/spec_build/spec_sw_build_loop.py",
                                         *(ROOT / "examples/spec_build/collateral/spec2017").glob("*.py"),
                                         *(ROOT / "examples/spec_build/collateral/spec2017").glob("*.sh")]}}
        save(args.run_dir / "invocation.json", invocation)
        try:
            require_guard()
            ray.init(**driver_options(os.environ["RAY_ADDRESS"]))
            run(config, args.run_dir, args.prepare_only)
        except Exception:
            save(args.run_dir / "failure.json", {"time": time.time(), "traceback": traceback.format_exc()})
            raise
        finally:
            ray.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
