"""Build pinned zstd CLIs and freeze real-source-code corpora for Rocket.

Outputs live outside Git. Native and QEMU runs are correctness checks only.
Run from the repository root with python -m examples.rocket_cost_model.prepare_zstd.
"""

import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile

REVISION = "f8745da6ff1ad1e7bab384bd1f9d742439278e99"
FLAGS = ["-O3", "-fno-tree-loop-vectorize", "-fno-tree-slp-vectorize"]
TARGET_FLAGS = ["-march=rv64imafdc", "-mabi=lp64d", "-mtune=rocket"]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def corpus(source: Path, paths: list[str], destination: Path) -> dict:
    """Archive actual application source files with fixed metadata and hashes."""
    records = []
    with tarfile.open(destination, "w", format=tarfile.USTAR_FORMAT) as archive:
        for name in sorted(paths):
            data = (source / name).read_bytes()
            member = tarfile.TarInfo(name)
            member.size, member.mode, member.mtime = len(data), 0o644, 0
            archive.addfile(member, io.BytesIO(data))
            records.append({"path": name, "sha256": hashlib.sha256(data).hexdigest()})
    return {"sha256": digest(destination), "bytes": destination.stat().st_size,
            "files": records, "kind": "real zstd application source, not generated data"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gcc", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=4, choices=range(1, 5))
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    if subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip() != REVISION:
        parser.error("source must be the pinned zstd v1.5.7 commit")
    # Export committed bytes, ignoring worktree build products or local edits.
    archive = subprocess.check_output(["git", "-C", str(source), "archive", "HEAD"])
    output.mkdir(parents=True, exist_ok=False)
    exported = output / "source"
    exported.mkdir()
    with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
        stream.extractall(exported, filter="data")
    (output / "corpora").mkdir()
    corpora = {}
    for label, directory in [("train", "lib/compress"), ("holdout", "lib/decompress")]:
        paths = [str(p.relative_to(exported)) for p in (exported / directory).rglob("*")
                 if p.is_file() and p.suffix in (".c", ".h")]
        if not paths:
            raise ValueError("empty application corpus")
        corpora[label] = corpus(exported, paths, output / "corpora" / (label + ".tar"))
    records = {}
    for label, compiler, extra in [("native", "cc", []), ("rocket", str(args.gcc.resolve()), TARGET_FLAGS)]:
        directory = output / label
        shutil.copytree(exported, directory)
        flags = [*FLAGS, *extra]
        command = ["make", "-C", str(directory / "programs"), f"-j{args.jobs}", "zstd",
                   "CC=" + compiler, "CFLAGS=" + " ".join(flags),
                   "LDFLAGS=" + ("-static" if label == "rocket" else ""),
                   "ZSTD_MULTITHREAD=0", "ZSTD_LEGACY_SUPPORT=0",
                   "HAVE_ZLIB=0", "HAVE_LZMA=0", "HAVE_LZ4=0"]
        with (output / (label + "-build.log")).open("w") as log:
            subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT, timeout=1800)
        binary = directory / "programs/zstd"
        version = subprocess.check_output([compiler, "--version"], text=True).splitlines()[0]
        records[label] = {"binary": str(binary), "sha256": digest(binary), "command": command,
                          "compiler_version": version, "compiler_sha256": digest(Path(shutil.which(compiler))),
                          "flags": flags}
    result = {"source_revision": REVISION, "source_archive_sha256": hashlib.sha256(archive).hexdigest(),
              "corpora": corpora, "builds": records, "FPGA_executed": False,
              "note": "Source-code corpora pilot; does not establish other compression-input generalization."}
    (output / "manifest.json").write_text(json.dumps(result, indent=2) + "\n")
    print(output / "manifest.json")


if __name__ == "__main__":
    main()
