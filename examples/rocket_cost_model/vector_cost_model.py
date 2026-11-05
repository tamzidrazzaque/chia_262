"""Build immutable GCC 15 frontends with bounded RISC-V vector-cost edits."""

from __future__ import annotations

import argparse
import difflib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import urllib.request


GCC_REVISION = "1b306039ac49f8ad91ca71d3de3150a3c9fa792a"
ARCHIVE_URL = f"https://codeload.github.com/gcc-mirror/gcc/tar.gz/{GCC_REVISION}"
ARCHIVE_SHA256 = "b45e06e72a265b129f0f68fc81b7be06c931e5ff7c2d47bafcd45c573eda96ad"
BASELINE_GCC_SHA256 = "e46d71073c10417353a0718bff6bfadb818757b887da2622d353926a26700b0c"
PRISTINE_RISCV_CC_SHA256 = "9c1ba4428cf65b884ae5b19e7d267760f77d5f22db5eac02a85df3ce31304f4f"
TARGET = "riscv64-unknown-linux-gnu-"

COMMON_COMMENTS = {
    "int_stmt": "int_stmt_cost",
    "fp_stmt": "fp_stmt_cost",
    "gather_load": "gather_load_cost",
    "scatter_store": "scatter_store_cost",
    **{f"segment_permute_{n}": f"segment_permute ({n})" for n in range(2, 9)},
    "vec_to_scalar": "vec_to_scalar_cost",
    "scalar_to_vec": "scalar_to_vec_cost",
    "permute": "permute_cost",
    "align_load": "align_load_cost",
    "align_store": "align_store_cost",
    "unalign_load": "unalign_load_cost",
    "unalign_store": "unalign_store_cost",
}
REGMOVE_COMMENTS = {
    "gr_to_vr": "GR2VR",
    "fr_to_vr": "FR2VR",
    "vr_to_gr": "VR2GR",
    "vr_to_fr": "VR2FR",
}
CPU_COMMENTS = {
    "scalar_int_stmt": "scalar_int_stmt_cost",
    "scalar_fp_stmt": "scalar_fp_stmt_cost",
    "scalar_load": "scalar_load_cost",
    "scalar_store": "scalar_store_cost",
    "cond_taken_branch": "cond_taken_branch_cost",
    "cond_not_taken_branch": "cond_not_taken_branch_cost",
}
BASE_COSTS = {
    **{key: (2 if key.startswith("unalign_") else 1) for key in COMMON_COMMENTS},
    **{key: 2 for key in REGMOVE_COMMENTS},
    **{key: (3 if key == "cond_taken_branch" else 1) for key in CPU_COMMENTS},
}


def sha256(path: Path) -> str:
    """Hash a source archive, compiler executable, or generated artifact."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_changes(changes: dict) -> dict:
    """Accept only documented integer vector-cost changes in a bounded range."""
    if not isinstance(changes, dict) or not changes:
        raise ValueError("proposal changes must be a nonempty object")
    unknown = changes.keys() - BASE_COSTS.keys()
    if unknown:
        raise ValueError(f"unknown vector-cost fields: {sorted(unknown)}")
    if any(type(value) is not int or not 1 <= value <= 64 for value in changes.values()):
        raise ValueError("vector costs must be integers from 1 to 64")
    return changes


def proposal(value: dict) -> dict:
    """Validate the tool-free role-3 proposal schema."""
    if not isinstance(value, dict) or value.keys() != {"changes", "rationale"}:
        raise ValueError("proposal must contain exactly changes and rationale")
    validate_changes(value["changes"])
    if not isinstance(value["rationale"], str) or not value["rationale"].strip() \
            or len(value["rationale"]) > 4000:
        raise ValueError("proposal rationale must be a nonempty string of at most 4000 characters")
    return value


def _replace_costs(body: str, comments: dict[str, str], values: dict[str, int]) -> str:
    for key, comment in comments.items():
        pattern = rf"(?m)^(\s*)\d+(,\s*/\*\s*{re.escape(comment)}\s*\*/)"
        body, count = re.subn(pattern, lambda match: f"{match[1]}{values[key]}{match[2]}", body)
        if count != 1:
            raise ValueError(f"expected one {comment} initializer, got {count}")
    return body


def _replace_block(source: str, declaration: str, comments: dict[str, str],
                   values: dict[str, int]) -> str:
    pattern = rf"({re.escape(declaration)}\s*=\s*\{{)(.*?)(\n\}};)"
    match = re.search(pattern, source, re.S)
    if not match:
        raise ValueError(f"pinned initializer was not found: {declaration}")
    body = _replace_costs(match[2], comments, values)
    return source[:match.start(2)] + body + source[match.end(2):]


def render_costs(original: str, changes: dict) -> tuple[str, dict[str, int]]:
    """Apply a bounded cost table and attach it to the Rocket tuning profile."""
    validate_changes(changes)
    values = {**BASE_COSTS, **changes}
    changed = _replace_block(
        original, "static const common_vector_cost rvv_vls_vector_cost",
        COMMON_COMMENTS, values,
    )
    changed = _replace_block(
        changed, "static const scalable_vector_cost rvv_vla_vector_cost",
        COMMON_COMMENTS, values,
    )
    changed = _replace_block(
        changed, "static const regmove_vector_cost rvv_regmove_vector_cost",
        REGMOVE_COMMENTS, values,
    )
    changed = _replace_block(
        changed, "static const struct cpu_vector_cost generic_vector_cost",
        CPU_COMMENTS, values,
    )
    rocket_pattern = r"(static const struct riscv_tune_param rocket_tune_info = \{)(.*?)(\n\};)"
    match = re.search(rocket_pattern, changed, re.S)
    if not match:
        raise ValueError("pinned rocket_tune_info was not found")
    body, count = re.subn(
        r"(?m)^\s*NULL(,\s*/\* vector cost \*/)",
        r"  &generic_vector_cost\1", match[2],
    )
    if count != 1:
        raise ValueError(f"expected one Rocket vector-cost pointer, got {count}")
    changed = changed[:match.start(2)] + body + changed[match.end(2):]
    return changed, values


def _source_record(root: Path, baseline: Path) -> dict:
    record = {
        "gcc_revision": GCC_REVISION,
        "archive_url": ARCHIVE_URL,
        "archive_sha256": ARCHIVE_SHA256,
        "pristine_riscv_cc_sha256": PRISTINE_RISCV_CC_SHA256,
        "baseline_gcc_sha256": BASELINE_GCC_SHA256,
        "baseline_prefix": str(baseline),
        "source": str(root / "source"),
    }
    prerequisites = {}
    for name in ("gmp", "mpfr", "mpc", "isl", "gettext"):
        directory = root / "source" / name
        configure = directory / "configure"
        if directory.exists() and configure.is_file():
            prerequisites[name] = {
                "source_directory": directory.resolve().name,
                "configure_sha256": sha256(configure),
            }
    if prerequisites:
        record["prerequisites"] = prerequisites
    return record


def _ensure_generated_lexer(root: Path) -> None:
    """Generate GCC's host lexer after a flex-less build left it absent or empty."""
    lexer = root / "build/gcc/gengtype-lex.cc"
    if lexer.is_file() and lexer.stat().st_size:
        return
    lexer.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["flex", "-o", str(lexer), str(root / "source/gcc/gengtype-lex.l")],
        check=True,
    )
    header = (
        '#ifdef HOST_GENERATOR_FILE\n#include "config.h"\n#else\n'
        '#include "bconfig.h"\n#endif\n'
    )
    lexer.write_text(header + lexer.read_text())
    # An interrupted make can retain an object built from an empty lexer.
    stale_object = root / "build/gcc/build/gengtype-lex.o"
    if stale_object.exists():
        stale_object.unlink()


def prepare(root: Path, baseline: Path) -> dict:
    """Pin source and configure an isolated GCC frontend build directory."""
    compiler = baseline / "bin" / (TARGET + "gcc")
    if not compiler.is_file() or sha256(compiler) != BASELINE_GCC_SHA256:
        raise ValueError("installed GCC differs from the audited role-2 baseline")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (root / "build.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        archive = root / f"gcc-{GCC_REVISION}.tar.gz"
        if not archive.exists():
            partial = archive.with_suffix(".partial")
            with urllib.request.urlopen(ARCHIVE_URL, timeout=120) as response, partial.open("wb") as stream:
                shutil.copyfileobj(response, stream)
            if sha256(partial) != ARCHIVE_SHA256:
                raise ValueError("downloaded GCC archive hash differs")
            partial.replace(archive)
        if sha256(archive) != ARCHIVE_SHA256:
            raise ValueError("GCC archive hash differs")
        source = root / "source"
        if not source.exists():
            unpack = root / "unpack"
            unpack.mkdir()
            with tarfile.open(archive) as stream:
                stream.extractall(unpack, filter="data")
            extracted = unpack / f"gcc-{GCC_REVISION}"
            extracted.rename(source)
            unpack.rmdir()
        backend = source / "gcc/config/riscv/riscv.cc"
        if sha256(backend) != PRISTINE_RISCV_CC_SHA256:
            raise ValueError("GCC RISC-V backend differs from the pinned revision")
        pristine = root / "pristine-riscv.cc"
        if not pristine.exists():
            shutil.copy2(backend, pristine)
        if sha256(pristine) != PRISTINE_RISCV_CC_SHA256:
            raise ValueError("pristine RISC-V backend hash differs")
        record = _source_record(root, baseline)
        manifest = root / "source.json"
        if manifest.exists():
            existing = json.loads(manifest.read_text())
            legacy = {key: value for key, value in record.items() if key != "prerequisites"}
            if existing not in (record, legacy):
                raise ValueError("existing vector compiler source identity differs")
        manifest.write_text(json.dumps(record, indent=2) + "\n")

        build = root / "build"
        build.mkdir(exist_ok=True)
        command = [
            str(source / "configure"), "--target=riscv64-unknown-linux-gnu",
            "--prefix=" + str(root / "unused-install"),
            "--with-sysroot=" + str(baseline / "sysroot"),
            "--with-pkgversion=g1b306039a", "--with-system-zlib",
            "--enable-shared", "--enable-tls", "--enable-languages=c,c++,fortran",
            "--disable-libmudflap", "--disable-libssp", "--disable-libquadmath",
            "--disable-libsanitizer", "--disable-nls", "--disable-bootstrap",
            "--disable-default-pie", "--disable-multilib", "--with-abi=lp64d",
            "--with-arch=rv64gc", "--with-isa-spec=20191213",
            "--with-as=" + str(baseline / "bin" / (TARGET + "as")),
            "--with-ld=" + str(baseline / "bin" / (TARGET + "ld")),
        ]
        recipe = root / "configure-command.json"
        if recipe.exists() and json.loads(recipe.read_text()) != command:
            raise ValueError("existing GCC configure recipe differs")
        recipe.write_text(json.dumps(command, indent=2) + "\n")
        if not (build / "Makefile").exists():
            with (root / "configure.log").open("w") as log:
                subprocess.run(command, cwd=build, check=True, stdout=log,
                               stderr=subprocess.STDOUT, timeout=900)
        _ensure_generated_lexer(root)
        return record


def _verify_snapshot(destination: Path) -> dict:
    record = json.loads((destination / "cost-model.json").read_text())
    for name, expected in record["file_hashes"].items():
        path = Path(name)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("unsafe compiler snapshot member")
        if sha256(destination / path) != expected:
            raise ValueError("immutable compiler snapshot changed")
    return record


def build_environment() -> dict:
    """Record the real host tools that compile the candidate frontends."""
    versions = {}
    for tool in ("gcc", "g++", "make", "flex", "bison", "file"):
        path = shutil.which(tool)
        if not path:
            raise ValueError(f"required GCC build tool is missing: {tool}")
        command = [path, "--version"] if tool != "file" else [path, "--version"]
        versions[tool] = subprocess.check_output(command, text=True).splitlines()[0]
    return {
        "platform": platform.platform(),
        "python": sys.version.splitlines()[0],
        "tools": versions,
        "runtime_image_id": os.environ.get("SATURN_BUILDER_IMAGE_ID"),
    }


def build_candidate(root: Path, baseline: Path, selected: dict, jobs: int = 4) -> dict:
    """Build one immutable role-3 frontend snapshot from a bounded proposal."""
    selected = proposal(selected)
    if type(jobs) is not int or not 1 <= jobs <= 8:
        raise ValueError("jobs must be from 1 to 8")
    source_record = prepare(root, baseline)
    pristine_path = root / "pristine-riscv.cc"
    original = pristine_path.read_text()
    changed, costs = render_costs(original, selected["changes"])
    environment = build_environment()
    identity = {
        "source": source_record,
        "costs": costs,
        "proposal": selected,
        "build_environment": environment,
    }
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    destination = root / "compilers" / key
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    manifest = destination / "cost-model.json"
    with (root / "build.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if manifest.exists():
            return _verify_snapshot(destination)
        backend = root / "source/gcc/config/riscv/riscv.cc"
        patch = "".join(difflib.unified_diff(
            original.splitlines(keepends=True), changed.splitlines(keepends=True),
            fromfile="a/gcc/config/riscv/riscv.cc", tofile="b/gcc/config/riscv/riscv.cc",
        ))
        (destination / "cost-model.diff").write_text(patch)
        backend.write_text(changed)
        command = ["make", f"-j{jobs}", "all-gcc"]
        try:
            with (destination / "build.log").open("w") as log:
                subprocess.run(command, cwd=root / "build", check=True, stdout=log,
                               stderr=subprocess.STDOUT, timeout=4 * 3600)
            frontend = destination / "frontends"
            frontend.mkdir()
            for name in ("cc1", "cc1plus", "f951", "collect2", "lto1", "lto-wrapper"):
                shutil.copy2(root / "build/gcc" / name, frontend / name)
        finally:
            backend.write_text(original)
        binary_dir = destination / "bin"
        binary_dir.mkdir()
        for language in ("gcc", "g++", "gfortran"):
            wrapper = binary_dir / (TARGET + language)
            driver = baseline / "bin" / wrapper.name
            wrapper.write_text(
                "#!/bin/sh\nexec " + shlex.quote(str(driver)) + " -B"
                + shlex.quote(str(destination / "frontends") + "/") + ' "$@"\n'
            )
            wrapper.chmod(0o755)
        for name in ("lib", "lib64", "sysroot"):
            source = baseline / name
            if source.exists():
                (destination / name).symlink_to(source, target_is_directory=True)
        artifacts = [destination / "cost-model.diff"]
        artifacts += list((destination / "bin").iterdir())
        artifacts += list((destination / "frontends").iterdir())
        record = {
            "candidate_id": key,
            "prefix": str(destination),
            "gcc_revision": GCC_REVISION,
            "baseline_prefix": str(baseline),
            "baseline_gcc_sha256": BASELINE_GCC_SHA256,
            "proposal": selected,
            "costs": costs,
            "source": source_record,
            "build_environment": environment,
            "build_command": command,
            "diff_sha256": hashlib.sha256(patch.encode()).hexdigest(),
            "file_hashes": {
                str(path.relative_to(destination)): sha256(path) for path in artifacts
            },
        }
        manifest.write_text(json.dumps(record, indent=2) + "\n")
        return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--baseline-prefix", type=Path, required=True)
    parser.add_argument("--proposal", type=Path)
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()
    root = args.root.resolve()
    baseline = args.baseline_prefix.resolve()
    if args.proposal is None:
        print(json.dumps(prepare(root, baseline), indent=2))
        return
    selected = proposal(json.loads(args.proposal.read_text()))
    record = build_candidate(root, baseline, selected, args.jobs)
    print(root / "compilers" / record["candidate_id"] / "cost-model.json")


if __name__ == "__main__":
    main()
