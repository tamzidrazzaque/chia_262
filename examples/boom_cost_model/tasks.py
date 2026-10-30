"""Chia worker stages for the bounded BOOM GCC experiment."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from ray import cloudpickle
from chia.base.ChiaFunction import ChiaFunction
from chia.chipyard import cost_model, spec_validation, measurements, boom_model
from chia.firesim.manager_node import FireSimManagerNode

cloudpickle.register_pickle_by_value(sys.modules[__name__])
cloudpickle.register_pickle_by_value(cost_model)
cloudpickle.register_pickle_by_value(boom_model)
cloudpickle.register_pickle_by_value(spec_validation)
cloudpickle.register_pickle_by_value(measurements)
cloudpickle.register_pickle_by_value(sys.modules["chia.firesim.manager_node"])


@ChiaFunction(resources={"riscv_build": 1}, max_retries=0)
def compiler_stage(root: str, prefix: str, costs: dict | None = None,
                   scheduling: dict | None = None, tuning: str = "rocket", move_profile: dict | None = None) -> dict:
    """Inspect the baseline or build a candidate on the selected compiler node."""
    if costs is None:
        return cost_model.compiler_identity(prefix)
    record = cost_model.build_compiler(root, prefix, costs, scheduling=scheduling, tuning=tuning, move_profile=move_profile)
    if costs == cost_model.BASE_COSTS and scheduling is None and tuning == "rocket":
        record["reproducibility"] = cost_model.check_unmodified_rebuild(record["prefix"], prefix,
                                                                      record["prefix"] + "/smoke")
    return record


@ChiaFunction(resources={"riscv_build": 1}, max_retries=0)
def validate_stage(outputs: dict[str, bytes], inputs: str) -> dict:
    """Compare this job's outputs using the installed native SPEC harness."""
    directory = "/tmp/spec_build/boom-validation/" + uuid.uuid4().hex
    return spec_validation.validate_outputs(outputs, os.environ["SPEC_DIR_2017"], directory, inputs)


@ChiaFunction(resources={"firemarshal": 1}, max_retries=0)
def build_diagnostics(descriptor: str) -> dict[str, bytes]:
    """Return the persisted SPEC compiler logs even when image composition failed."""
    name = Path(descriptor).stem
    if "/" in descriptor or name in ("", ".", ".."):
        raise ValueError("unsafe descriptor")
    directory = Path("/images") / (name + "-build-logs")
    if not directory.is_dir():
        raise FileNotFoundError("SPEC compiler diagnostics were not persisted")
    return {str(p.relative_to(directory)): p.read_bytes() for p in directory.rglob("*") if p.is_file()}


@ChiaFunction(resources={"firemarshal": 1}, max_retries=0)
def qemu_stage(descriptor: str, timeout: int = 900, memory_mb: int = 2048) -> list[dict]:
    """Boot test images with networking disabled; collect guest results privately."""
    import json
    from chia.cluster.loopback import require_guard
    require_guard()
    if type(memory_mb) is not int or not 2048 <= memory_mb <= 12288:
        raise ValueError("QEMU memory must be from 2048 to 12288 MiB")
    name = Path(descriptor).stem
    if name != descriptor.removesuffix(".json") or "/" in name or name in ("", ".", ".."):
        raise ValueError("unsafe workload descriptor")
    source = Path("/images") / name
    config = json.loads((source / (name + ".json")).read_text())
    base = Path("/images") / (name + "-qemu-" + uuid.uuid4().hex[:8])
    base.mkdir()
    records = []
    for job in config["workloads"]:
        directory = base / job["name"]
        directory.mkdir()
        image = directory / "rootfs.img"
        subprocess.run(["cp", "--sparse=always", str(source / job["rootfs"]), str(image)], check=True)
        args = ["qemu-system-riscv64", "-nographic", "-bios", "none", "-smp", "1",
                "-machine", "virt", "-m", str(memory_mb), "-kernel", str(source / job["bootbinary"]),
                "-nic", "none", "-device", "virtio-blk-device,drive=hd0",
                "-drive", f"file={image},format=raw,id=hd0"]
        try:
            proc = subprocess.run(["bash", "-lc", 'source /home/ray/chipyard/env.sh >/dev/null; exec "$@"', "_", *args],
                                  capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            uart = (exc.stdout or b"") + (exc.stderr or b"")
            (directory / "uart.log").write_bytes(uart)
            records.append({"name": job["name"], "success": False, "returncode": -1,
                            "uart": uart, "outputs": {}, "command": args,
                            "failure": f"QEMU timeout after {timeout} seconds", "FPGA_executed": False})
            break
        uart = proc.stdout + proc.stderr
        (directory / "uart.log").write_bytes(uart)
        mount = directory / "mount"
        mount.mkdir()
        subprocess.run(["mount", "-t", "ext4", "-o", "ro,loop,noload", str(image), str(mount)], check=True)
        try:
            shutil.copytree(mount / "output", directory / "output")
            outputs = {str(p.relative_to(directory)): p.read_bytes()
                       for p in (directory / "output").rglob("*") if p.is_file()}
        finally:
            subprocess.run(["umount", str(mount)], check=True)
        # Remove only this disposable image after successful collection.
        image.unlink()
        record = {"name": job["name"], "success": proc.returncode == 0 and b"Power down" in uart,
                  "returncode": proc.returncode, "uart": uart, "outputs": outputs, "command": args,
                  "FPGA_executed": False}
        records.append(record)
        if not record["success"]:
            break
    return records


@ChiaFunction(resources={"firesim_fpga": 1}, max_retries=0)
def fpga_stage(job, bitstream, config, timeout_seconds: int = 24 * 3600):
    """Use the existing matching hardware; runtime policy refuses occupied slots."""
    from chia.cluster.loopback import require_guard
    require_guard()
    os.environ["CHIA_FIRESIM_SKIP_DEBUG_SERVERS"] = "1"
    os.environ["CHIA_FIRESIM_PREPARED_SDK_REVISION"] = "434775d5fc098d08b100dd5494302e84ba2165a4"
    if type(timeout_seconds) is not int or not 60 <= timeout_seconds <= 7 * 24 * 3600:
        raise ValueError("FPGA timeout must be from 60 seconds to seven days")
    result = FireSimManagerNode(timeout_seconds=timeout_seconds).run_job(job, bitstream, config)
    if result.success:
        try:
            reclaimed = compact_completed_spec_image(result.benchmark_name)
            print(f"Compacted completed SPEC staging image: {reclaimed} bytes reclaimed", flush=True)
        except Exception as exc:
            # A measured result remains valid even if storage maintenance fails.
            print(f"SPEC staging image compaction failed: {exc}", file=sys.stderr, flush=True)
    return result


def compact_completed_spec_image(name: str, root: Path = Path("/home/ubuntu/sim_slot_0")) -> int:
    """Sparsify this completed job's rootfs copies while preserving every byte."""
    if not re.fullmatch(r"spec17-intspeed-(?:test|train|ref)-[0-9a-f]{8}-[0-9]{3}\.[a-z0-9_]+_s", name):
        raise ValueError("unexpected SPEC workload name")
    running = subprocess.run(["pgrep", "-af", "FireSim-f2"], capture_output=True, text=True, check=False)
    if any("./FireSim-f2 " in line for line in running.stdout.splitlines()):
        raise RuntimeError("FireSim driver is still running")
    image_name = f"{name}0-{name}.img"
    reclaimed = 0
    for parent in (root / "rsyncdir", root):
        image = parent / image_name
        if not image.exists():
            continue
        before = image.lstat()
        if not image.is_file() or image.is_symlink() or before.st_nlink != 1:
            raise RuntimeError(f"unsafe SPEC staging image: {image}")
        if str(image) in Path("/proc/mounts").read_text():
            raise RuntimeError(f"SPEC staging image is mounted: {image}")
        loops = subprocess.run(["losetup", "-j", str(image)], capture_output=True, text=True, check=True)
        if loops.stdout.strip():
            raise RuntimeError(f"SPEC staging image is attached to a loop device: {image}")
        def digest():
            h = hashlib.sha256()
            with image.open("rb") as stream:
                for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                    h.update(block)
            return h.digest()
        original = digest()
        subprocess.run(["fallocate", "--dig-holes", str(image)], check=True)
        if digest() != original:
            raise RuntimeError(f"SPEC staging image changed during compaction: {image}")
        reclaimed += (before.st_blocks - image.stat().st_blocks) * 512
    return reclaimed


@ChiaFunction(resources={"firemarshal": 1}, max_retries=0)
def workload_fingerprints(descriptor: str) -> dict:
    """Hash pristine image contents read-only, including all guest runtime files."""
    import hashlib
    import json
    import tempfile
    if Path(descriptor).name != descriptor or not descriptor.endswith(".json") or \
            Path(descriptor).stem in ("", ".", ".."):
        raise ValueError("unsafe workload descriptor")
    source = Path("/images") / Path(descriptor).stem
    config = json.loads((source / descriptor).read_text())
    provenance = Path("/images") / (Path(descriptor).stem + "-build-logs") / "compiler-provenance.json"
    compiler_prefix = ""
    if provenance.exists():
        compiler = json.loads(provenance.read_text())["compilers"]["riscv_gcc"]["path"]
        compiler_prefix = str(Path(compiler).parent.parent)
    result = {}
    with tempfile.TemporaryDirectory(prefix="chia-fingerprint-") as temporary:
        mount = Path(temporary)
        for job in config["workloads"]:
            for key in ("rootfs", "bootbinary"):
                if Path(job[key]).name != job[key]:
                    raise ValueError("unsafe workload asset path")
            subprocess.run(["mount", "-t", "ext4", "-o", "ro,loop,noload",
                            str(source / job["rootfs"]), str(mount)], check=True)
            try:
                filesystem = measurements.tree_identity(mount, compiler_prefix)
                executables = {str(p.relative_to(mount)): hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in (mount / "root/spec").rglob("*_base.riscv-64")
                               if not p.is_symlink() and p.is_file()}
            finally:
                subprocess.run(["umount", str(mount)], check=True)
            result[job["name"]] = {"filesystem": filesystem,
                "executables": executables,
                "boot_sha256": hashlib.sha256((source / job["bootbinary"]).read_bytes()).hexdigest(),
                "job": {k: v for k, v in job.items() if k not in ("name", "rootfs", "bootbinary")}}
    return result


@ChiaFunction(resources={"firesim_fpga": 0.001}, max_retries=0)
def fpga_worker_identity() -> dict:
    from chia.firesim.manager_node import _public_ip
    from chia.cluster.loopback import require_guard
    import ray
    require_guard()
    return {"ip": _public_ip(), "node_id": ray.get_runtime_context().get_node_id(),
            "bind_ip": os.environ.get("CHIA_LOOPBACK_BIND_IP")}
