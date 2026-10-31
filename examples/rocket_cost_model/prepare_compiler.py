"""Prepare the handoff's pinned GCC rebuild natively inside an isolated worker.

This is compiler software setup only. It does not install over the original
compiler, execute benchmarks, or interact with AWS/FPGA hardware.
"""

import argparse
import fcntl
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import urllib.request

from chia.chipyard.cost_model import (BASELINE_GCC_SHA256, BASE_COSTS, GCC_REVISION,
                                      TARGET, build_compiler, check_unmodified_rebuild, sha256)

ARCHIVE_SHA256 = "47478252fe8b890a43396707349bfe4a013426dc63d43dd14a0c5dff2a6fe952"
URL = f"https://codeload.github.com/gcc-mirror/gcc/tar.gz/{GCC_REVISION}"


def prepare(root: Path, prefix: Path):
    """Verify the original compiler and configure an independent frontend build."""
    if sha256(prefix / "bin" / (TARGET + "gcc")) != BASELINE_GCC_SHA256:
        raise ValueError("original GCC differs from the audited baseline")
    root.mkdir(parents=True, exist_ok=True)
    with (root / "build.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        archive = root / "gcc-source.tar.gz"
        if not archive.exists():
            partial = archive.with_suffix(".partial")
            with urllib.request.urlopen(URL, timeout=120) as response, partial.open("wb") as stream:
                shutil.copyfileobj(response, stream)
            if sha256(partial) != ARCHIVE_SHA256:
                raise ValueError("pinned GCC source archive hash differs")
            partial.replace(archive)
        if sha256(archive) != ARCHIVE_SHA256:
            raise ValueError("pinned GCC source archive hash differs")
        if not (root / "source").exists():
            unpack = root / "unpack"
            unpack.mkdir(exist_ok=False)
            with tarfile.open(archive) as stream:
                stream.extractall(unpack, filter="data")
            (unpack / ("gcc-" + GCC_REVISION)).rename(root / "source")
            unpack.rmdir()
        pristine = root / "pristine-riscv.cc"
        backend = root / "source/gcc/config/riscv/riscv.cc"
        if not pristine.exists():
            shutil.copy2(backend, pristine)
        record = {"gcc_revision": GCC_REVISION, "archive_url": URL,
                  "archive_sha256": ARCHIVE_SHA256, "riscv_cc_sha256": sha256(pristine),
                  "feedstock_revision": "56c29e0", "toolchain_revision": "9a28c809a5d355874def06a414aa5f272fae564d"}
        manifest = root / "source.json"
        if manifest.exists() and json.loads(manifest.read_text()) != record:
            raise ValueError("existing compiler source identity differs")
        manifest.write_text(json.dumps(record, indent=2) + "\n")
        build = root / "build"
        build.mkdir(exist_ok=True)
        deps = prefix.parent
        command = [str(root / "source/configure"), "--target=riscv64-unknown-linux-gnu",
                   "--prefix=" + str(prefix), "--with-sysroot=" + str(prefix / "sysroot"),
                   "--with-pkgversion=gc891d8dc23e", "--with-system-zlib", "--enable-shared", "--enable-tls",
                   "--enable-languages=c,c++,fortran", "--disable-libmudflap", "--disable-libssp",
                   "--disable-libquadmath", "--disable-libsanitizer", "--disable-nls", "--disable-bootstrap",
                   "--disable-multilib", "--with-abi=lp64d", "--with-arch=rv64imafdc", "--with-tune=rocket",
                   "--with-isa-spec=20191213", *["--with-" + dep + "=" + str(deps) for dep in ("gmp", "mpfr", "mpc")],
                   "--with-as=" + str(prefix / "bin" / (TARGET + "as")),
                   "--with-ld=" + str(prefix / "bin" / (TARGET + "ld")),
                   f"LDFLAGS=-L{deps}/lib -Wl,-rpath,{deps}/lib"]
        recipe = root / "configure-command.json"
        if recipe.exists() and json.loads(recipe.read_text()) != command:
            raise ValueError("existing GCC configure recipe differs")
        recipe.write_text(json.dumps(command, indent=2) + "\n")
        if not (build / "Makefile").exists():
            with (root / "configure.log").open("w") as log:
                subprocess.run(command, cwd=build, check=True, stdout=log, stderr=subprocess.STDOUT, timeout=600)
        lexer = build / "gcc/gengtype-lex.cc"
        if not lexer.exists():
            lexer.parent.mkdir(exist_ok=True)
            subprocess.run(["flex", "-o", str(lexer), str(root / "source/gcc/gengtype-lex.l")], check=True)
            lexer.write_text('#ifdef HOST_GENERATOR_FILE\n#include "config.h"\n#else\n#include "bconfig.h"\n#endif\n' + lexer.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--baseline-prefix", type=Path, required=True)
    args = parser.parse_args()
    root, prefix = args.root.resolve(), args.baseline_prefix.resolve()
    prepare(root, prefix)
    compiler = build_compiler(str(root), str(prefix), BASE_COSTS)
    compiler["reproducibility"] = check_unmodified_rebuild(compiler["prefix"], str(prefix), compiler["prefix"] + "/smoke")
    (root / "unchanged-rebuild.json").write_text(json.dumps(compiler, indent=2) + "\n")
    print(root / "unchanged-rebuild.json")


if __name__ == "__main__":
    main()
