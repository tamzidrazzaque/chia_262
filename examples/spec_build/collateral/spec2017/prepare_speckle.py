"""Configure the inspected SPEC2017 Speckle pin inside the compiler worker.

Only host tool paths, build parallelism and result handling are adjusted. The
RISC-V compiler and default optimization/ISA/ABI flags remain those of the pin.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

PIN = "07f845d381965900b5c1c1f11db8980d1b238f20"


def configure(directory: Path, flags: str = "") -> dict:
    revision = subprocess.check_output(["git", "-C", str(directory), "rev-parse", "HEAD"],
                                       text=True).strip()
    if revision != PIN:
        raise ValueError(f"SPEC2017 requires Speckle {PIN}, found {revision}")
    if "\n" in flags or "\r" in flags:
        raise ValueError("SPEC_FLAGS must be a single line")
    riscv = Path(os.environ["RISCV"])
    compilers = {}
    for family, prefix in (("host", Path("/usr")), ("riscv", riscv)):
        for language in ("gcc", "g++", "gfortran"):
            path = prefix / "bin" / (("riscv64-unknown-linux-gnu-" if family == "riscv" else "") + language)
            version = subprocess.check_output([str(path), "--version"], text=True).splitlines()[0]
            compilers[f"{family}_{language}"] = {
                "path": str(path), "version": version,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
    configs = {}
    for filename in ("host.cfg", "riscv.cfg", "gen_binaries.sh"):
        original = subprocess.check_output(["git", "-C", str(directory), "show", f"{PIN}:{filename}"], text=True)
        text = original
        if filename == "host.cfg":
            text = text.replace("%{/usr/}", "/usr")
            text = re.sub(r"(sw_compiler001\s*=).*", rf"\1 {compilers['host_gcc']['version']}", text)
        if filename.endswith(".cfg"):
            text = re.sub(r"(define\s+build_ncpus\s+)\d+", r"\g<1>4", text)
            text = re.sub(r"^(ignore_errors\s*=\s*)1", r"\g<1>0", text, flags=re.M)
        if filename == "riscv.cfg" and flags:
            text = re.sub(r"^([ \t]*(?:CC|CXX|FC)[ \t]*=.*)$",
                          lambda match: match[1] + " " + flags, text, flags=re.M)
        if filename == "gen_binaries.sh":
            text = text.replace("REDIRECT=false", "REDIRECT=true")
            # A functional check can select real benchmarks without rebuilding
            # the entire suite; the default still builds the pinned full suite.
            text = text.replace("--action build ${suite_type}",
                                "--action build ${SPEC_BENCHMARKS:-$suite_type}")
            text = text.replace("--action runsetup ${suite_type}",
                                "--action runsetup ${SPEC_BENCHMARKS:-$suite_type}")
            text = re.sub(r"^(benchmarks=\$\(basename.*)$",
                          lambda match: match[1] + '\nif [ -n "${SPEC_BENCHMARKS:-}" ]; then '
                          'benchmarks="$SPEC_BENCHMARKS"; fi', text, flags=re.M)
        (directory / filename).write_text(text)
        configs[filename] = {"pinned_sha256": hashlib.sha256(original.encode()).hexdigest(),
                             "configured_sha256": hashlib.sha256(text.encode()).hexdigest()}
    record = {"speckle_revision": revision, "spec_flags": flags, "compilers": compilers,
              "configs": configs, "build_ncpus": 4}
    (directory.parent / "compiler-provenance.json").write_text(json.dumps(record, indent=2) + "\n")
    return record


def finish(directory: Path, suite: str, size: str) -> None:
    overlay = directory / "build/overlay" / suite / size
    scripts = list(overlay.glob("*/run*.sh"))
    if not scripts:
        raise FileNotFoundError(f"Speckle generated no run scripts in {overlay}")
    for path in scripts:
        text = path.read_text()
        text = text.replace("#!/bin/bash\n", "#!/bin/bash\nset -e\n", 1)
        path.write_text(text)
    # Replace the pin's result wrapper, which writes to ~/output and loses
    # benchmark exit codes. This does not alter the benchmark commands.
    wrapper = Path(__file__).with_name("run_spec2017.sh")
    shutil.copyfile(wrapper, overlay / f"{suite}.sh")
    (overlay / f"{suite}.sh").chmod(0o755)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--finish", nargs=2, metavar=("SUITE", "INPUT"))
    args = parser.parse_args()
    if args.finish:
        finish(args.directory, *args.finish)
    else:
        print(json.dumps(configure(args.directory, os.environ.get("SPEC_FLAGS", "")), indent=2))
