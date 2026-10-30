"""Content identities and validated measurement reuse for private experiments."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import stat
import tarfile

from chia.chipyard.cost_model import BASELINE_GCC_SHA256
from chia.chipyard.spec_validation import completion_status, real_time

AUDITED_SPEC_WRAPPER_SHA256 = "35bb2f6661ae43a16f61c7fb754a736d88f2a3782e6eee43bc99e48381feb2bd"


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def normalize_native_environment(path: str, data: bytes, compiler_prefix: str) -> bytes:
    """Canonicalize only the selected build-host compiler location in metadata.

    The pinned guest wrapper executes run.sh, not these native harness files.
    Preserve every actual command, tolerance, other environment entry and PATH
    component. The prefix comes from this workload's compiler provenance.
    """
    if not compiler_prefix or not re.fullmatch(
            r"root/spec/intspeed/(test|train|ref)/[0-9]{3}\.[A-Za-z0-9_]+/(compare|speccmds)\.cmd", path):
        return data
    try:
        text = data.decode()
    except UnicodeDecodeError:
        return data
    lines = text.splitlines(keepends=True)
    riscv = [i for i, line in enumerate(lines) if line.startswith("-E RISCV ")]
    paths = [i for i, line in enumerate(lines) if line.startswith("-E PATH ")]
    if len(riscv) != 1 or len(paths) != 1 or lines[riscv[0]].strip() != "-E RISCV " + compiler_prefix:
        return data
    entries = lines[paths[0]].removeprefix("-E PATH ").rstrip("\n").split(":")
    selected = compiler_prefix + "/bin"
    if selected not in entries:
        return data
    entries[entries.index(selected)] = "<selected-build-compiler>/bin"
    lines[paths[0]] = "-E PATH " + ":".join(entries) + "\n"
    lines[riscv[0]] = "-E RISCV <selected-build-compiler>\n"
    return "".join(lines).encode()


def tree_identity(root: Path, compiler_prefix: str = "") -> dict:
    """Hash filesystem contents, permissions and ownership, excluding timestamps.

    Never follow links. Include every file. Only native metadata's selected
    build-host compiler location is canonicalized, with raw hashes retained.
    Runtime scripts, input files, commands, and comparison tolerances stay exact.
    """
    if compiler_prefix:
        wrappers = list((root / "root/spec/intspeed").glob("*/intspeed.sh"))
        if len(wrappers) != 1 or wrappers[0].is_symlink() or \
                hashlib.sha256(wrappers[0].read_bytes()).hexdigest() != AUDITED_SPEC_WRAPPER_SHA256:
            compiler_prefix = ""
    records = []
    raw_records = []
    normalized = []
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        record = [str(path.relative_to(root)), info.st_mode, info.st_uid, info.st_gid]
        if stat.S_ISREG(info.st_mode):
            h = hashlib.sha256()
            with path.open("rb") as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    h.update(block)
            raw = h.hexdigest()
            canonical = raw
            relative = str(path.relative_to(root))
            if compiler_prefix and path.name in ("compare.cmd", "speccmds.cmd") and info.st_size < 1024 * 1024:
                canonical = hashlib.sha256(normalize_native_environment(
                    relative, path.read_bytes(), compiler_prefix)).hexdigest()
                if canonical != raw:
                    normalized.append(relative)
            raw_records.append([*record, raw])
            record.append(canonical)
        elif stat.S_ISLNK(info.st_mode):
            record.append(str(path.readlink()))
        elif stat.S_ISCHR(info.st_mode) or stat.S_ISBLK(info.st_mode):
            record.append(info.st_rdev)
        elif not (stat.S_ISDIR(info.st_mode) or stat.S_ISFIFO(info.st_mode)):
            raise ValueError("unsupported runtime filesystem entry")
        records.append(record)
        if not stat.S_ISREG(info.st_mode):
            raw_records.append(record)
    return {"sha256": digest(records), "entries": len(records), "raw_sha256": digest(raw_records),
            "normalization_policy": "spec2017-native-compiler-location-v1", "normalized_metadata": normalized}


def measurement_key(fingerprint: dict, hardware: dict, runtime_sha256: str,
                    instance_id: str, inputs: str, repeat: int) -> str:
    """Keep physical workers, independent repeats and input sizes distinct."""
    # Executable hashes are explanatory telemetry, already covered by the full
    # filesystem hash. Adding telemetry must not invalidate a recovered sample.
    identity = {k: v for k, v in fingerprint.items() if k != "executables"}
    if "filesystem" in identity:
        identity["filesystem"] = {k: v for k, v in identity["filesystem"].items()
                                  if k not in ("raw_sha256", "normalized_metadata")}
    return digest([identity, hardware, runtime_sha256, instance_id, inputs, repeat])


def validated_cache(directory: Path, key: str) -> tuple[dict, dict] | None:
    """Recheck saved bytes and completion before returning an existing sample."""
    path = directory / (key + ".json")
    if not path.exists():
        return None
    record = json.loads(path.read_text())
    source = Path(record["source"])
    correct = json.loads((source / "correctness.json").read_text())
    if not correct.get("success"):
        raise ValueError("cached measurement is not validated")
    outputs = {str(p.relative_to(source / "collected")): p.read_bytes()
               for p in (source / "collected").rglob("*") if p.is_file()}
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in outputs.items()}
    if record["key"] != key or hashes != record["output_hashes"]:
        raise ValueError("cached measurement bytes changed")
    completion_status(outputs)
    if real_time(outputs) != record["real_time"]:
        raise ValueError("cached measurement time changed")
    return record, outputs


def prior_train_evidence(directories: list[str], hardware: dict) -> list[dict]:
    """Import only train observations; never expose held-out results to proposals.

    Prior measurements are context, not scores in the new experiment. Refuse
    another baseline/target and preserve individual benchmark observations.
    """
    evidence = []
    for name in directories:
        root = Path(name)
        baseline = json.loads((root / "baseline-identity.json").read_text())
        old_hardware = json.loads((root / "hardware.json").read_text())
        if baseline["drivers"]["gcc"]["sha256"] != BASELINE_GCC_SHA256 or any(
                old_hardware[k] != hardware[k]
                for k in ("AGFI", "driver_bundle_sha256", "Chipyard_revision", "FireSim_revision")):
            raise ValueError("prior experiment baseline or hardware differs")
        base = json.loads((root / "baseline-f2/train/evaluation.json").read_text())
        history = json.loads((root / "progress.json").read_text())["history"]
        observations = []
        def executable_hashes(stage, benchmark):
            archives = list((root / stage / "train/0").glob(
                "*/collected/*/output/" + benchmark + ".run.tar"))
            if len(archives) != 1:
                return None
            with tarfile.open(archives[0]) as archive:
                return {Path(m.name).name: hashlib.sha256(archive.extractfile(m).read()).hexdigest()
                        for m in archive.getmembers() if m.isfile() and "_base.riscv-64" in m.name}
        original_binaries = {b: executable_hashes("baseline-f2", b) for b in base["times"]}
        for item in history:
            if not item.get("success"):
                continue
            times = item["train_times"]
            if times.keys() != base["times"].keys() or any(
                    not math.isfinite(v) or v <= 0 for v in [*times.values(), *base["times"].values()]):
                raise ValueError("invalid prior train observations")
            same = {}
            for benchmark in times:
                actual = executable_hashes(f"candidate-{item['index']:03d}-f2", benchmark) if "index" in item else None
                same[benchmark] = (actual == original_binaries[benchmark]
                                   if actual and original_binaries[benchmark] else None)
            observations.append({"costs": item["proposal"]["costs"], "train_times": times,
                                 "executable_identical_to_baseline": same})
        evidence.append({"source": str(root), "baseline_train_times": base["times"],
                         "observations": observations,
                         "interpretation": "Single-run train observations; small differences do not establish optimality. "
                                           "Do not infer causality from prior model rationales."})
    return evidence
