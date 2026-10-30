"""Bounded GCC cost-table edits and immutable compiler frontend snapshots.

Run rebuilds inside the existing compiler worker. The installed driver, target
libraries, ISA, ABI, scheduler and compiler source revision stay fixed.
"""

from __future__ import annotations

import fcntl
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess

from chia.chipyard import boom_model

GCC_REVISION = "c891d8dc23e1a46ad9f3e757d09e57b500d40044"
BASELINE_GCC_SHA256 = "28b629f64ed9797dc198621eb5cfcb63c0a48e17b95c639bada20f14038e77e4"
BASE_COSTS = {"fp_add": [4, 5], "fp_mul": [4, 5], "fp_div": [20, 20],
              "int_mul": [4, 4], "int_div": [6, 6], "branch_cost": 3,
              "memory_cost": 5, "fmv_cost": 8}
TARGET = "riscv64-unknown-linux-gnu-"
FLAGS = ["-O3", "-static", "-march=rv64imafdc", "-mabi=lp64d"]
BACKEND_HASHES = {
    "riscv-cores.def": "6be76e997d710efe580853d4364dfdeca3f086ef065727b98dd6e642762fceae",
    "riscv-opts.h": "c03036efe30a80b2ae09a0e4174f8f7b4b497ea1b06cfe6a43e94f1b79516acb",
    "riscv.md": "79b7e8b15254098a60c8b737d1e482ea2c44032ae5b6c5b17906d1f11a46dfbf",
}


def sha256(path: Path) -> str:
    """Hash a file, including a compiler executable."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_costs(values: dict) -> dict:
    """Accept a complete cost table containing only bounded integer costs."""
    if not isinstance(values, dict) or values.keys() != BASE_COSTS.keys():
        raise ValueError("proposal must contain exactly the documented cost fields")
    for key, default in BASE_COSTS.items():
        val = values[key]
        entries = val if isinstance(default, list) else [val]
        if isinstance(default, list) and (not isinstance(val, list) or len(val) != 2):
            raise ValueError(f"{key} requires two costs")
        if any(type(v) is not int or not 1 <= v <= 64 for v in entries):
            raise ValueError(f"{key} costs must be integers from 1 to 64")
    return values


def render_costs(original: str, values: dict) -> str:
    """Replace numeric costs solely in rocket_tune_info; preserve scheduling."""
    validate_costs(values)
    pattern = r"(static const struct riscv_tune_param rocket_tune_info = \{)(.*?)(\n\};)"
    match = re.search(pattern, original, re.S)
    if not match:
        raise ValueError("pinned rocket_tune_info was not found")
    body = match[2]
    for key, value in values.items():
        replacement = ("{" + ", ".join(f"COSTS_N_INSNS ({v})" for v in value) + "}"
                       if isinstance(value, list) else str(value))
        body, count = re.subn(r"(?m)^[ \t]*[^\n]+?(,\s*/\* " + key + r" \*/)",
                              lambda m: "  " + replacement + m[1], body)
        if count != 1:
            raise ValueError(f"expected one pinned {key} initializer")
    return original[:match.start(2)] + body + original[match.end(2):]


def validate_scheduling(values: dict) -> dict:
    """Bound the separate issue-rate experiment; do not accept arbitrary edits."""
    if not isinstance(values, dict) or values.keys() != {"issue_rate"} or \
            type(values["issue_rate"]) is not int or not 1 <= values["issue_rate"] <= 8:
        raise ValueError("scheduling requires an integer issue_rate from 1 to 8")
    return values


def render_scheduling(original: str, values: dict) -> str:
    validate_scheduling(values)
    pattern = r"(static const struct riscv_tune_param rocket_tune_info = \{)(.*?)(\n\};)"
    match = re.search(pattern, original, re.S)
    if not match:
        raise ValueError("pinned rocket_tune_info was not found")
    body, count = re.subn(r"(?m)^[ \t]*\d+(,\s*/\* issue_rate \*/)",
                          lambda m: f"  {values['issue_rate']}" + m[1], match[2])
    if count != 1:
        raise ValueError("expected one pinned issue_rate initializer")
    return original[:match.start(2)] + body + original[match.end(2):]


def compiler_identity(prefix: str) -> dict:
    """Record all three selected compiler drivers and immutable manifest data."""
    directory = Path(prefix)
    records = {}
    for language in ("gcc", "g++", "gfortran"):
        path = directory / "bin" / (TARGET + language)
        records[language] = {"path": str(path), "sha256": sha256(path),
                             "version": subprocess.check_output([str(path), "--version"], text=True).splitlines()[0]}
    manifest = directory / "cost-model.json"
    snapshot = _verify_snapshot(directory) if manifest.is_file() else None
    return {"prefix": prefix, "drivers": records,
            "manifest": snapshot}


def _verify_snapshot(directory: Path) -> dict:
    record = json.loads((directory / "cost-model.json").read_text())
    for name, expected in record["file_hashes"].items():
        path = Path(name)
        if path.is_absolute() or ".." in path.parts or len(path.parts) != 2 or path.parts[0] not in ("bin", "frontends"):
            raise ValueError("invalid compiler snapshot member")
        if sha256(directory / path) != expected:
            raise ValueError("immutable compiler snapshot changed")
    return record


def build_compiler(root: str, baseline_prefix: str, values: dict, jobs: int = 4,
                   scheduling: dict | None = None, tuning: str = "rocket", move_profile: dict | None = None) -> dict:
    """Rebuild pinned GCC frontends, leaving the installed baseline untouched.

    ``root`` must contain source/, source.json and an already configured build/.
    The source manifest pins the archive and pristine RISC-V backend hash.
    A lock serializes the shared incremental build. Each successful candidate
    copies frontends into a fresh content-keyed prefix before releasing it.
    """
    validate_costs(values)
    if tuning not in ("rocket", "boom"):
        raise ValueError("tuning must be rocket or boom")
    if move_profile is not None:
        if tuning != "boom":
            raise ValueError("directional move profile is BOOM-only")
        boom_model.validate_move_profile(move_profile)
    if type(jobs) is not int or not 1 <= jobs <= 4:
        raise ValueError("jobs must be from 1 to 4")
    base = Path(root)
    original_prefix = Path(baseline_prefix)
    if sha256(original_prefix / "bin" / (TARGET + "gcc")) != BASELINE_GCC_SHA256:
        raise ValueError("installed baseline compiler identity changed")
    pin = json.loads((base / "source.json").read_text())
    if pin["gcc_revision"] != GCC_REVISION:
        raise ValueError("GCC revision differs from installed compiler")
    original = (base / "pristine-riscv.cc").read_text()
    if hashlib.sha256(original.encode()).hexdigest() != pin["riscv_cc_sha256"]:
        raise ValueError("pristine backend hash differs")
    changed = render_costs(original, values)
    identity = [pin, values]
    if scheduling is not None:
        changed = render_scheduling(changed, scheduling)
        identity.append(validate_scheduling(scheduling))
    if tuning == "boom":
        identity.append({"tuning": tuning, "model_version": boom_model.MODEL_VERSION,
                         "scheduler_sha256": hashlib.sha256(boom_model.scheduling_description().encode()).hexdigest(),
                         "issue_rate": (scheduling or {}).get("issue_rate", 4)})
    if move_profile is not None:
        identity.append({"move_profile": move_profile, "version": boom_model.MOVE_PROFILE_VERSION})
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    destination = base / "compilers" / key
    with (base / "build.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        manifest = destination / "cost-model.json"
        if manifest.exists():
            return _verify_snapshot(destination)
        backend_dir = base / "source/gcc/config/riscv"
        originals = {"riscv.cc": original}
        for name, expected in BACKEND_HASHES.items():
            pristine = base / ("pristine-" + name)
            data = pristine.read_bytes() if pristine.exists() else (backend_dir / name).read_bytes()
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError(f"pinned backend changed: {name}")
            if not pristine.exists():
                pristine.write_bytes(data)
            originals[name] = data.decode()
        sources = {**originals, "riscv.cc": changed}
        if tuning == "boom":
            sources = boom_model.render_sources(originals, values, (scheduling or {}).get("issue_rate", 4), move_profile)
        for name, text in sources.items():
            target = backend_dir / name
            if not target.exists() or target.read_text() != text:
                target.write_text(text)
        destination.mkdir(parents=True, exist_ok=True)
        patch = "".join("".join(difflib.unified_diff(originals.get(name, "").splitlines(keepends=True),
                    text.splitlines(keepends=True), fromfile="a/gcc/config/riscv/" + name,
                    tofile="b/gcc/config/riscv/" + name)) for name, text in sources.items())
        (destination / "cost-model.diff").write_text(patch)
        libraries = str(original_prefix.parent / "lib")
        command = ["make", f"-j{jobs}", "all-gcc", f"LDFLAGS=-L{libraries} -Wl,-rpath,{libraries}"]
        with (destination / "build.log").open("w") as log:
            subprocess.run(command, cwd=base / "build", stdout=log, stderr=subprocess.STDOUT,
                           check=True, timeout=4 * 3600)
        frontend = destination / "frontends"
        frontend.mkdir(exist_ok=True)
        for name in ("cc1", "cc1plus", "f951", "collect2", "lto1", "lto-wrapper"):
            shutil.copy2(base / "build/gcc" / name, frontend / name)
        (destination / "bin").mkdir(exist_ok=True)
        for language in ("gcc", "g++", "gfortran"):
            wrapper = destination / "bin" / (TARGET + language)
            wrapper.write_text("#!/bin/sh\nexec " + shlex.quote(str(original_prefix / "bin" / wrapper.name))
                               + " -B" + shlex.quote(str(frontend) + "/")
                               + (" -mtune=boom" if tuning == "boom" else "") + ' "$@"\n')
            wrapper.chmod(0o755)
        # Speckle uses this prefix to locate runtime libraries too. Reuse exactly
        # the baseline libraries; never install over or patch the original tree.
        for name in ("lib", "lib64", "sysroot"):
            source = original_prefix / name
            link = destination / name
            if source.exists() and not link.exists():
                link.symlink_to(source, target_is_directory=True)
        record = {"compiler_id": key, "prefix": str(destination), "gcc_revision": GCC_REVISION,
                  "baseline_prefix": baseline_prefix, "baseline_gcc_sha256": BASELINE_GCC_SHA256,
                  "costs": values, "source": pin, "build_command": command,
                  "diff_sha256": hashlib.sha256(patch.encode()).hexdigest(),
                  "configure": (base / "build/configargs.h").read_text() if (base / "build/configargs.h").exists() else "see configure.log",
                  "file_hashes": {str(p.relative_to(destination)): sha256(p)
                                  for folder in ("bin", "frontends") for p in (destination / folder).iterdir()}}
        if scheduling is not None:
            record["scheduling"] = scheduling
        if move_profile is not None:
            record["move_profile"] = move_profile
            record["move_profile_version"] = boom_model.MOVE_PROFILE_VERSION
        if tuning == "boom":
            record.update(tuning="boom", model_version=boom_model.MODEL_VERSION,
                          model_assumptions=boom_model.ASSUMPTIONS,
                          boom_revision=boom_model.SOURCE_REVISION,
                          source_hashes={name: hashlib.sha256(text.encode()).hexdigest()
                                         for name, text in sources.items()})
        manifest.write_text(json.dumps(record, indent=2) + "\n")
        return record


def check_unmodified_rebuild(prefix: str, baseline_prefix: str, directory: str) -> dict:
    """Require unchanged code generation for C, C++ and Fortran and link all three.

    This is a reproducibility gate, not a claim of binary-identical host tools.
    The performance baseline remains the original installed compiler.
    """
    work = Path(directory)
    work.mkdir(parents=True, exist_ok=True)
    examples = {"gcc": ("smoke.c", "long f(long x){return x*7+x/3;} int main(){return f(9)!=66;}\n"),
                "g++": ("smoke.cpp", "long f(long x){return x*7+x/3;} int main(){return f(9)!=66;}\n"),
                "gfortran": ("smoke.f90", "program smoke\ninteger :: i\ni=9\nif (i*7+i/3 /= 66) stop 1\nend program smoke\n")}
    records = {}
    for language, (filename, source) in examples.items():
        path = work / filename
        path.write_text(source)
        outputs = []
        for label, selected in (("baseline", baseline_prefix), ("rebuilt", prefix)):
            asm = work / (language + "." + label + ".s")
            cc = str(Path(selected) / "bin" / (TARGET + language))
            subprocess.run([cc, *FLAGS, "-S", str(path), "-o", str(asm)], check=True)
            subprocess.run([cc, *FLAGS, str(path), "-o", str(work / (language + "." + label))], check=True)
            outputs.append(asm.read_bytes())
        if outputs[0] != outputs[1]:
            raise ValueError(f"unmodified {language} rebuild changes smoke assembly; inspect {work}")
        records[language] = {"unchanged_assembly": True, "static_link": True,
                             "sha256": hashlib.sha256(outputs[0]).hexdigest()}
    return records
