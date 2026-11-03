"""Run one verified zstd pilot on the current F2 from a dedicated runtime container.

Requires --privileged, --pid=host and the owned /home/ubuntu bind mount, following
CHIA's existing FireSim runtime. No Ray cluster or cloud provisioning is started.
The owner launches long runs in their own tmux. An unverified manifest is rejected.
"""

import argparse
import dataclasses
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
from urllib.request import Request, urlopen

from chia.chipyard import rocket_target as target
from chia.chipyard.state_def import FireMarshalArtifact
from chia.firesim.fs_bitstream import FSBitstream
from chia.firesim.manager_node import FireSimManagerNode
from chia.firesim.state_def import RunConfig
from examples.rocket_cost_model.zstd_results import validate, measurement_key
from examples.rocket_cost_model.validate_zstd_guest import validate_archive


def host(command):
    """Run a checked command on the owned host through the runtime's namespaces."""
    return subprocess.check_output(["sudo", "-n", "nsenter", "-t", "1", "-a", "--", "sudo", "-n", "-H",
                                    "-u", "ubuntu", "/bin/bash", "-lc", command], text=True, timeout=30)


def instance_id():
    """Read the current physical worker identity using IMDSv2 with finite waits."""
    imds = "http://169.254.169.254/latest"
    token = urlopen(Request(imds + "/api/token", method="PUT",
        headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"}), timeout=5).read().decode()
    return urlopen(Request(imds + "/meta-data/instance-id",
        headers={"X-aws-ec2-metadata-token": token}), timeout=5).read().decode()


def check_idle_slot():
    """Refuse any occupied driver, unknown SDK or loaded image mismatch."""
    host("if pgrep -x FireSim-f2 >/dev/null; then echo 'active FPGA driver' >&2; exit 1; fi")
    if host("git -C /home/ubuntu/aws-fpga rev-parse HEAD").strip() != target.SDK:
        raise ValueError("worker SDK differs from the Rocket pin")
    slot = host("sudo -n fpga-describe-local-image -S 0 -H")
    if not {target.AGFI, "loaded", "0x10212415"}.issubset(set(slot.split())):
        raise ValueError("worker's loaded Rocket image/shell differs")
    return slot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hardware", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--phase", choices=("pilot", "search", "confirmation", "holdout"), default="pilot")
    parser.add_argument("--sample", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=3600)
    args = parser.parse_args()
    if args.sample < 0 or not 60 <= args.timeout <= 86400:
        parser.error("invalid sample index or timeout")
    hardware = json.loads(args.hardware.read_text())
    target.validate_hardware(hardware)
    if instance_id() != args.instance_id:
        raise ValueError("runtime is not on the selected physical worker")
    # The dedicated worker's host bind mount gives every runtime the same lock.
    with Path("/home/ubuntu/rocket-runtime.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = check_idle_slot()
        args.output.mkdir(parents=True, exist_ok=False)
        (args.output / "slot-before.log").write_text(before)
        identity = json.loads((args.image / "identity.json").read_text())
        archive = (args.image / "workload.tar.gz").read_bytes()
        validate_archive(archive)
        source = FireMarshalArtifact(archive=archive,
            json_name=(args.image / "descriptor.txt").read_text().strip())
        jobs = source.split()
        if len(jobs) != 1:
            raise ValueError("one application job required")
        staged = args.output / "image"
        staged.mkdir()
        descriptor = jobs[0].unpack(str(staged))
        def sha(path):
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                    digest.update(block)
            return digest.hexdigest()
        software = {**identity, "rootfs_sha256": sha(staged / descriptor["common_rootfs"]),
            "bootbinary_sha256": sha(staged / descriptor["common_bootbinary"]),
            "runtime_sha256": sha(args.runtime)}
        key = measurement_key(software, hardware, args.instance_id, args.phase, args.sample)
        (args.output / "measurement-identity.json").write_text(json.dumps({"key": key,
            "software": software, "hardware": hardware, "worker": args.instance_id,
            "phase": args.phase, "sample": args.sample}, indent=2) + "\n")
        os.environ["CHIA_FIRESIM_SKIP_DEBUG_SERVERS"] = "1"
        os.environ["CHIA_FIRESIM_PREPARED_SDK_REVISION"] = target.SDK
        bitstream = FSBitstream(target.QUINTUPLET, agfi=target.AGFI,
                                driver_bytes=Path(hardware["driver_bundle"]).read_bytes())
        node = FireSimManagerNode(timeout_seconds=args.timeout, watch_status=False)
        # The public run_job adapter adds Ray placement metadata. This dedicated
        # local path instead verifies the physical host explicitly via IMDS above.
        result = node._run(args.instance_id, jobs[0], bitstream, RunConfig.from_yaml(str(args.runtime)))
        (args.output / "manager.log").write_text(result.log)
        (args.output / "uart.log").write_text(result.uartlog)
        (args.output / "completion.json").write_text(json.dumps({k: v for k, v in dataclasses.asdict(result).items()
            if k not in ("outputs", "log", "uartlog")}, indent=2) + "\n")
        for name, data in result.outputs.items():
            path = Path(name)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("unsafe collected output")
            dest = args.output / "collected" / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        evidence = validate(result.outputs, identity["input_sha256"], identity["binary_sha256"], result.success, "fpga")
        (args.output / "slot-after.log").write_text(check_idle_slot())
        (args.output / "correctness.json").write_text(json.dumps(evidence, indent=2) + "\n")
        print(args.output / "correctness.json")


if __name__ == "__main__":
    main()
