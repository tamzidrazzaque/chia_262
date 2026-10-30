"""Prepare the pinned GCC rebuild in a bind-mounted, existing compiler worker.

Downloads on the controller only. Uses existing host flex and worker GMP/MPFR/
MPC, adds no packages, installs nothing over the baseline, and changes no ports.
"""

import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import tarfile
import urllib.request

from chia.chipyard.cost_model import GCC_REVISION, BASELINE_GCC_SHA256

ARCHIVE_SHA256 = "47478252fe8b890a43396707349bfe4a013426dc63d43dd14a0c5dff2a6fe952"
URL = f"https://codeload.github.com/gcc-mirror/gcc/tar.gz/{GCC_REVISION}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host-root", type=Path, required=True)
    parser.add_argument("--worker-root", required=True)
    parser.add_argument("--worker", required=True)
    parser.add_argument("--docker-group", default="docker")
    args = parser.parse_args()
    base = args.host_root.resolve()
    base.mkdir(parents=True, exist_ok=True)
    lock = (base / "build.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX)
    def docker(*command, **kwargs):
        return subprocess.run(["sg", args.docker_group, "-c", shlex.join(["docker", "exec", args.worker, *command])],
                              check=True, **kwargs)
    probe = ('import hashlib,json,os,pathlib; r=pathlib.Path(os.environ["RISCV"]); '
             'print(json.dumps({"prefix":str(r),"sha256":hashlib.sha256((r/"bin/riscv64-unknown-linux-gnu-gcc").read_bytes()).hexdigest()}))')
    compiler = json.loads(docker("python", "-c", probe, capture_output=True, text=True).stdout)
    if compiler["sha256"] != BASELINE_GCC_SHA256:
        raise ValueError("worker does not contain the pinned baseline")
    if not (base / "source").exists():
        archive = base / "gcc-source.tar.gz"
        if not archive.exists():
            urllib.request.urlretrieve(URL, archive)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != ARCHIVE_SHA256:
            raise ValueError("GCC source archive hash mismatch")
        unpack = base / "unpack"
        unpack.mkdir(exist_ok=False)
        with tarfile.open(archive) as source:
            source.extractall(unpack, filter="data")
        (unpack / ("gcc-" + GCC_REVISION)).rename(base / "source")
        unpack.rmdir()
    backend = base / "source/gcc/config/riscv/riscv.cc"
    if not (base / "source.json").exists():
        shutil.copy2(backend, base / "pristine-riscv.cc")
        (base / "source.json").write_text(json.dumps({"gcc_revision": GCC_REVISION,
            "archive_url": URL, "archive_sha256": ARCHIVE_SHA256,
            "riscv_cc_sha256": hashlib.sha256(backend.read_bytes()).hexdigest(),
            "feedstock_revision": "56c29e0", "toolchain_revision": "9a28c809a5d355874def06a414aa5f272fae564d"}, indent=2) + "\n")
    pin = json.loads((base / "source.json").read_text())
    if pin["gcc_revision"] != GCC_REVISION or pin["archive_sha256"] != ARCHIVE_SHA256:
        raise ValueError("existing source manifest differs")
    (base / "build").mkdir(exist_ok=True)
    # Confirm that the caller supplied matching host and worker bind paths.
    marker = hashlib.sha256((base / "source.json").read_bytes()).hexdigest()
    verify = 'import pathlib,hashlib,sys; assert hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest()==sys.argv[2]'
    docker("python", "-c", verify, args.worker_root + "/source.json", marker)
    prefix = compiler["prefix"]
    dependencies = str(Path(prefix).parent)
    command = [args.worker_root + "/source/configure", "--target=riscv64-unknown-linux-gnu",
               "--prefix=" + prefix, "--with-sysroot=" + prefix + "/sysroot", "--with-pkgversion=gc891d8dc23e",
               "--with-system-zlib", "--enable-shared", "--enable-tls", "--enable-languages=c,c++,fortran",
               "--disable-libmudflap", "--disable-libssp", "--disable-libquadmath", "--disable-libsanitizer",
               "--disable-nls", "--disable-bootstrap", "--disable-multilib", "--with-abi=lp64d",
               "--with-arch=rv64imafdc", "--with-tune=rocket", "--with-isa-spec=20191213",
               "--with-gmp=" + dependencies, "--with-mpfr=" + dependencies, "--with-mpc=" + dependencies,
               "--with-as=" + prefix + "/bin/riscv64-unknown-linux-gnu-as",
               "--with-ld=" + prefix + "/bin/riscv64-unknown-linux-gnu-ld",
               "LDFLAGS=-L" + dependencies + "/lib -Wl,-rpath," + dependencies + "/lib"]
    (base / "configure-command.json").write_text(json.dumps(command, indent=2) + "\n")
    if not (base / "build/Makefile").exists():
        with (base / "configure.log").open("w") as log:
            docker("bash", "-lc", 'cd "$1"; shift; exec "$@"', "_", args.worker_root + "/build", *command,
                   stdout=log, stderr=subprocess.STDOUT)
    lexer = base / "build/gcc/gengtype-lex.cc"
    if not lexer.exists():
        lexer.parent.mkdir(exist_ok=True)
        subprocess.run(["flex", "-o", str(lexer), str(base / "source/gcc/gengtype-lex.l")], check=True)
        header = '#ifdef HOST_GENERATOR_FILE\n#include "config.h"\n#else\n#include "bconfig.h"\n#endif\n'
        lexer.write_text(header + lexer.read_text())
    with (base / "rebuild.log").open("w") as log:
        docker("bash", "-lc", 'cd "$1"; exec make -j4 all-gcc "$2"', "_", args.worker_root + "/build",
               "LDFLAGS=-L" + dependencies + "/lib -Wl,-rpath," + dependencies + "/lib",
               stdout=log, stderr=subprocess.STDOUT)
    print("Pinned GCC rebuild prepared; run the loop's --prepare-only correctness gates next.")


if __name__ == "__main__":
    main()
