"""Validate collected real-zstd application evidence before admitting timings."""

import hashlib
import json
import math
from pathlib import PurePosixPath
import re


def measurement_key(software: dict, hardware: dict, worker: str, phase: str, sample: int) -> str:
    """Separate target/runtime, physical workers, search/confirmation and repeats."""
    if phase not in ("pilot", "search", "confirmation", "holdout") or type(sample) is not int or sample < 0 or not worker:
        raise ValueError("invalid independent measurement identity")
    required = ("binary_sha256", "input_sha256", "runner_sha256", "rootfs_sha256",
                "bootbinary_sha256", "runtime_sha256")
    if any(not re.fullmatch(r"[0-9a-f]{64}", software.get(field, "")) for field in required):
        raise ValueError("incomplete software/runtime measurement identity")
    if not hardware.get("AGFI") or not hardware.get("quintuplet") or not re.fullmatch(
            r"[0-9a-f]{64}", hardware.get("driver_bundle_sha256", "")):
        raise ValueError("incomplete hardware measurement identity")
    return hashlib.sha256(json.dumps([software, hardware, worker, phase, sample], sort_keys=True).encode()).hexdigest()


def validate(outputs: dict[str, bytes], input_sha256: str, binary_sha256: str,
             simulation_success: bool, backend: str) -> dict:
    """Require completed execution, exact decoded bytes and finite elapsed time.

    Args:
        outputs: Bytes collected by FireSim/QEMU from this job's /output folder.
        input_sha256: Hash of the pinned real corpus supplied to the guest.
        binary_sha256: Hash of the exact selected zstd executable.
        simulation_success: Completion status from the execution adapter.
        backend: Explicit label, either fpga, qemu or native. Functional runs
            remain distinguishable and must never enter hardware selection.
    """
    if simulation_success is not True or backend not in ("fpga", "qemu", "native"):
        raise ValueError("execution incomplete or backend unknown")
    for value in (input_sha256, binary_sha256):
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError("missing workload identity")
    files = {}
    for name, data in outputs.items():
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or path.name in files:
            raise ValueError("unsafe or ambiguous output path")
        files[path.name] = data
    for status in ("job.status", "collection.status"):
        if files.get(status, b"").strip() != b"0":
            raise ValueError("application or collection failed")
    if files.get("correctness.txt", b"").strip() != b"correct":
        raise ValueError("guest round trip did not pass")
    if hashlib.sha256(files.get("decoded.tar", b"")).hexdigest() != input_sha256:
        raise ValueError("decoded bytes differ from the original corpus")
    def declared_hashes(data):
        result = []
        for line in data.decode().splitlines():
            match = re.fullmatch(r"([0-9a-f]{64}) [ *].+", line)
            if match is None:
                raise ValueError("malformed checksum record")
            result.append(match[1])
        return result
    hashes = declared_hashes(files.get("inputs.sha256", b""))
    if len(hashes) != 2 or hashes != [binary_sha256, input_sha256]:
        raise ValueError("guest executable/input identity differs")
    for field in ("compressed.zst", "decoded.tar"):
        if not files.get(field):
            raise ValueError("application output missing")
    declared = declared_hashes(files.get("outputs.sha256", b""))
    actual = [hashlib.sha256(files[name]).hexdigest() for name in ("compressed.zst", "decoded.tar")]
    if len(declared) != 2 or declared != actual:
        raise ValueError("collected output hashes differ")
    times = {}
    for operation in ("compress", "decompress"):
        match = re.fullmatch(rb"real ([0-9]+(?:\.[0-9]+)?)\s*", files.get(operation + ".time", b""))
        if match is None:
            raise ValueError("missing or malformed application timing")
        value = float(match[1])
        if not math.isfinite(value) or value <= 0:
            raise ValueError("nonpositive or invalid application timing")
        times[operation] = value
    return {"success": True, "backend": backend, "FPGA_executed": backend == "fpga",
            "seconds": times, "input_sha256": input_sha256, "binary_sha256": binary_sha256,
            "compressed_bytes": len(files["compressed.zst"]),
            "output_hashes": {k: hashlib.sha256(v).hexdigest() for k, v in outputs.items()}}
