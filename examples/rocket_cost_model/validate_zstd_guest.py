"""Boot one composed zstd Linux image in QEMU and collect functional evidence.

Requires a disposable privileged build worker for read-only loop mounting.
QEMU networking is disabled. No timing from this command is a Rocket label.
"""

import argparse
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile

from chia.chipyard.state_def import FireMarshalArtifact
from examples.rocket_cost_model.zstd_results import validate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True, help="zstd_image_job output directory")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--qemu", default="qemu-system-riscv64")
    args = parser.parse_args()
    if not 30 <= args.timeout <= 3600:
        parser.error("QEMU timeout must be 30..3600 seconds")
    archive = (args.image / "workload.tar.gz").read_bytes()
    with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
        for member in stream.getmembers():
            path = Path(member.name)
            if path.is_absolute() or len(path.parts) != 1 or not member.isfile():
                raise ValueError("unexpected composed workload member")
    args.output.mkdir(parents=True, exist_ok=False)
    args.output = args.output.resolve()
    unpacked = args.output / "unpacked"
    unpacked.mkdir()
    artifact = FireMarshalArtifact(archive=archive, json_name=(args.image / "descriptor.txt").read_text().strip())
    descriptor = artifact.unpack(str(unpacked))
    jobs = descriptor.get("workloads", [])
    if len(jobs) != 1:
        raise ValueError("expected one zstd guest job")
    job = jobs[0]
    for key in ("rootfs", "bootbinary"):
        if len(Path(job[key]).parts) != 1:
            raise ValueError("unsafe guest image filename")
    rootfs = args.output / "qemu-rootfs.img"
    subprocess.run(["cp", "--sparse=always", str(unpacked / job["rootfs"]), str(rootfs)], check=True)
    command = [args.qemu, "-nographic", "-bios", "none", "-smp", "1", "-machine", "virt", "-m", "2048",
               "-kernel", str(unpacked / job["bootbinary"]), "-nic", "none",
               "-device", "virtio-blk-device,drive=hd0", "-drive", f"file={rootfs},format=raw,id=hd0"]
    completion = {"success": False, "FPGA_executed": False, "command": command}
    try:
        try:
            result = subprocess.run(command, capture_output=True, timeout=args.timeout)
            uart = result.stdout + result.stderr
            completion["returncode"] = result.returncode
            complete = result.returncode == 0 and (b"Power down" in uart or b"Power off" in uart)
        except subprocess.TimeoutExpired as exc:
            uart = (exc.stdout or b"") + (exc.stderr or b"")
            complete = False
            completion.update(returncode=-1, failure="QEMU guest timeout")
        (args.output / "uart.log").write_bytes(uart)
        if not complete:
            raise RuntimeError("guest did not complete and power down; inspect UART")
        mount = args.output / "mount"
        mount.mkdir()
        subprocess.run(["sudo", "-n", "mount", "-t", "ext4", "-o", "ro,loop,noload", str(rootfs), str(mount)], check=True)
        try:
            shutil.copytree(mount / "output", args.output / "collected")
        finally:
            subprocess.run(["sudo", "-n", "umount", str(mount)], check=True)
        collected = args.output / "collected"
        outputs = {str(p.relative_to(collected)): p.read_bytes() for p in collected.rglob("*") if p.is_file()}
        identity = json.loads((args.image / "identity.json").read_text())
        evidence = validate(outputs, identity["input_sha256"], identity["binary_sha256"], True, "qemu")
        (args.output / "correctness.json").write_text(json.dumps(evidence, indent=2) + "\n")
        completion["success"] = True
        rootfs.unlink()
    finally:
        (args.output / "completion.json").write_text(json.dumps(completion, indent=2) + "\n")
    print(args.output / "correctness.json")


if __name__ == "__main__":
    main()
