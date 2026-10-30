"""Check collected SPEC2017 outputs using the user's installed native tools.

No benchmark sources or reference outputs are included in this module. The
same gates apply to test, train and ref inputs. QEMU timings are never scored.
"""

from __future__ import annotations

import csv
import io
import math
from pathlib import Path
import re
import shlex
import subprocess
import tarfile


def completion_status(outputs: dict[str, bytes]) -> dict:
    """Require benchmark, job and output-collection statuses, all exactly zero."""
    statuses = {}
    archives = []
    for name, data in outputs.items():
        short = Path(name).name
        if short.endswith((".status", ".collection-status")):
            if short in statuses:
                raise ValueError("ambiguous status filename")
            statuses[short] = data.decode().strip()
        if short.endswith(".run.tar"):
            archives.append(short)
    if len(archives) != 1:
        raise ValueError("expected one collected benchmark archive per job")
    label = archives[0].removesuffix(".run.tar")
    required = {"job.status", label + ".status", label + ".collection-status"}
    if statuses.keys() != required or any(s != "0" for s in statuses.values()):
        raise ValueError(f"incomplete or failed benchmark/collection: {statuses}")
    return statuses


def extract_run(data: bytes, destination: Path) -> None:
    """Extract regular files/directories only, rejecting traversal and links."""
    destination.mkdir(parents=True, exist_ok=False)
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        for member in archive.getmembers():
            path = Path(member.name)
            if path.is_absolute() or ".." in path.parts or not (member.isfile() or member.isdir()):
                raise ValueError("unsafe collected archive member")
        archive.extractall(destination, filter="data")


def validate_outputs(outputs: dict[str, bytes], spec_dir: str, work_dir: str,
                     inputs: str) -> dict:
    """Run native specinvoke -E with unchanged SPEC comparison tolerances.

    Run in the compiler worker after sourcing SPEC's shrc. Native runsetup
    references must still exist. Comparison failures, missing commands and
    collection failures all prevent scoring. The caller saves returned logs.
    """
    if inputs not in ("test", "train", "ref"):
        raise ValueError("unknown SPEC input size")
    statuses = completion_status(outputs)
    data = next(data for name, data in outputs.items() if name.endswith(".run.tar"))
    directory = Path(work_dir)
    extract_run(data, directory)
    original = directory / "compare.cmd"
    lines = original.read_text().splitlines()
    dirs = [Path(line[3:]) for line in lines if line.startswith("-C ")]
    if len(dirs) != 1 or not dirs[0].is_absolute():
        raise ValueError("expected one absolute SPEC comparison working directory")
    spec = Path(spec_dir).resolve()
    if not dirs[0].resolve().is_relative_to(spec):
        raise ValueError("comparison references another SPEC installation")
    expected_size = "refspeed" if inputs == "ref" else inputs
    if not dirs[0].name.startswith("run_base_" + expected_size + "_"):
        raise ValueError("comparison input size does not match workload")
    def helper(match):
        path = (dirs[0] / match[1]).resolve()
        if not path.is_relative_to(spec) or not path.is_file():
            raise ValueError("native comparison helper missing")
        return shlex.quote(str(path))
    lines = [("-C " + str(directory)) if line.startswith("-C ") else
             re.sub(r"(?<!\S)(\.\./run_base_\S+/imagevalidate_[A-Za-z0-9_.-]+)", helper, line)
             for line in lines]
    comparisons = sum("/harness/specdiff " in line for line in lines)
    if not comparisons:
        raise ValueError("no native SPEC comparisons collected")
    command_file = directory / "compare.collected.cmd"
    command_file.write_text("\n".join(lines) + "\n")
    command = [str(spec / "bin/specinvoke"), "-E", str(command_file)]
    proc = subprocess.run(["bash", "-c", 'set -e; cd "$1"; source shrc; cd "$2"; exec "$3" -E "$4"',
                           "_", str(spec), str(directory), *command[:1], str(command_file)],
                          cwd=directory, capture_output=True, text=True, timeout=600)
    miscompares = [p.name for p in directory.glob("*.mis")]
    return {"success": proc.returncode == 0 and not miscompares, "inputs": inputs,
            "guest_statuses": statuses, "comparison_count": comparisons,
            "returncode": proc.returncode, "miscompares": miscompares,
            "command": command, "log": proc.stdout + proc.stderr}


def real_time(outputs: dict[str, bytes]) -> float:
    """Read one positive finite guest RealTime; require complete collection."""
    completion_status(outputs)
    files = [data for name, data in outputs.items() if name.endswith(".csv")]
    if len(files) != 1:
        raise ValueError("expected one benchmark timing CSV")
    rows = list(csv.DictReader(io.StringIO(files[0].decode())))
    if len(rows) != 1:
        raise ValueError("expected one timing row")
    value = float(rows[0]["RealTime"])
    if not math.isfinite(value) or value <= 0:
        raise ValueError("invalid guest time")
    return value


def relative_speedup(baseline: dict[str, float], candidate: dict[str, float]) -> float:
    """Geometric mean of per-job speedups for identical benchmark/input sets."""
    if not baseline or baseline.keys() != candidate.keys():
        raise ValueError("baseline and candidate jobs differ")
    vals = [*baseline.values(), *candidate.values()]
    if any(not math.isfinite(v) or v <= 0 for v in vals):
        raise ValueError("invalid timing")
    return math.exp(sum(math.log(baseline[k] / candidate[k]) for k in baseline) / len(baseline))
