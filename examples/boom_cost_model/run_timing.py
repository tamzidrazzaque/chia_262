"""Compile tune variants and compare cycle counts on a Chipyard simulator.

The harness/runtime use an existing Chipyard GCC; only kernels use the
experimental GCC and tuning flags. Host checks validate correctness only.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import statistics
import subprocess

TUNES = ("rocket", "generic-ooo", "xiangshan-nanhu")
KERNELS = ("branchy", "int_mix", "dot", "saxpy")
SAMPLES = 6
SIZES = (32, 128, 512)
PATTERNS = ("mixed", "low", "high", "random")


def parse_suite_results(text):
    """Require every size/pattern/tune/kernel cell with three valid samples."""
    if "SUITE_OK sizes=32,128,512 patterns=4 repeats=2 samples=3" not in text:
        raise ValueError("Suite did not report successful correctness checks")
    rows = {}
    for line in text.splitlines():
        if not line.startswith("S "):
            continue
        fields = line.split()
        if len(fields) != 8:
            raise ValueError(f"Malformed suite measurement: {line}")
        n, pattern, kernel, tune, *samples = map(int, fields[1:])
        key = (n, pattern, kernel, tune)
        if (n not in SIZES or not 0 <= pattern < len(PATTERNS)
                or not 0 <= kernel < len(KERNELS) or not 0 <= tune < len(TUNES)
                or min(samples) <= 0 or key in rows):
            raise ValueError(f"Invalid or duplicate suite measurement: {line}")
        rows[key] = samples
    if len(rows) != len(SIZES) * len(PATTERNS) * len(KERNELS) * len(TUNES):
        raise ValueError("Incomplete suite measurements")
    summary = []
    for n in SIZES:
        for p, pattern in enumerate(PATTERNS):
            for k, kernel in enumerate(KERNELS):
                baseline = statistics.median(rows[n, p, k, 0])
                for t, tune in enumerate(TUNES):
                    samples = rows[n, p, k, t]
                    median = statistics.median(samples)
                    summary.append({"n": n, "pattern": pattern, "kernel": kernel,
                                    "tune": tune, "cycles": samples, "median_cycles": median,
                                    "min_cycles": min(samples), "max_cycles": max(samples),
                                    "speedup": baseline / median})
    return summary


def parse_results(text):
    """Validate complete, positive cycle measurements and correctness marker."""
    if "CHECKS_OK n=128 repeats=8 samples=6" not in text:
        raise ValueError("Simulator did not report successful correctness checks")
    rows = {}
    for kernel, tune, sample, cycles in re.findall(
        r"^RESULT (\S+) (\S+) (\d+) (\d+)\s*$", text, re.MULTILINE
    ):
        key = (kernel, tune, int(sample))
        if kernel not in KERNELS or tune not in TUNES or not 0 <= int(sample) < SAMPLES:
            raise ValueError(f"Unexpected measurement: {key}")
        if key in rows or int(cycles) <= 0:
            raise ValueError(f"Duplicate or nonpositive measurement: {key}")
        rows[key] = int(cycles)
    if len(rows) != len(KERNELS) * len(TUNES) * SAMPLES:
        raise ValueError("Incomplete measurements")
    summary = []
    for kernel in KERNELS:
        baseline = statistics.median(rows[kernel, "rocket", s] for s in range(SAMPLES))
        for tune in TUNES:
            samples = [rows[kernel, tune, s] for s in range(SAMPLES)]
            median = statistics.median(samples)
            summary.append({"kernel": kernel, "tune": tune, "cycles": samples,
                            "median_cycles": median, "min_cycles": min(samples),
                            "max_cycles": max(samples), "speedup": baseline / median})
    return summary


def file_hash(path):
    """Return a SHA256 fingerprint of an experiment input."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(experiment=None):
    """Run the historical suite or an explicitly supplied experiment profile."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gcc", type=Path, required=True, help="GCC supporting all three tunes")
    parser.add_argument("--runtime-gcc", type=Path, required=True, help="Chipyard GCC with htif_nano.specs")
    parser.add_argument(
        "--runtime-specs",
        default="htif_nano.specs",
        help="GCC specs name or absolute path used to link the HTIF runtime",
    )
    parser.add_argument("--simulator", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--opt", choices=("O2", "O3"), default="O2")
    parser.add_argument("--suite", action="store_true", help="Vary sizes and input patterns")
    parser.add_argument("--layout", type=int, choices=(0, 1, 2), default=0,
                        help="Rotate the tune order when linking kernels")
    parser.add_argument("--dramsim-ini", type=Path, help="Chipyard DRAMSim2 configuration directory")
    parser.add_argument("--timeout", type=int, default=600, help="Simulator wall-clock timeout in seconds")
    args = parser.parse_args()
    if experiment is not None and args.suite:
        parser.error("--suite applies only to the historical branch/float experiment")
    kernels = experiment["kernels"] if experiment else KERNELS
    harness_name = experiment["harness"] if experiment else "timing.c"
    alignment = experiment["alignment"] if experiment else 64
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    for path in (args.gcc, args.runtime_gcc, args.simulator):
        if not path.is_file():
            parser.error(f"Missing executable: {path}")
    if args.dramsim_ini is not None and not args.dramsim_ini.is_dir():
        parser.error("--dramsim-ini must be an existing directory")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    # A failed rerun must not leave a previous speedup report looking current.
    for name in ("results.json", "REPORT.txt"):
        (out / name).unlink(missing_ok=True)
    source = Path(__file__).resolve().parent
    common = ["-march=rv64gc", "-mabi=lp64d", "-mcmodel=medany", "-fno-lto"]
    commands = []

    def run(command):
        commands.append([str(arg) for arg in command])
        subprocess.run(command, check=True)

    objects = []
    for tune in TUNES:
        for kernel in kernels:
            obj = out / f"{kernel}.{tune}.o"
            symbol = f"{kernel}_{tune.replace('-', '_')}"
            run([args.gcc.resolve(), *common, f"-{args.opt}", f"-mtune={tune}",
                 f"-falign-functions={alignment}", *(experiment.get("kernel_flags", []) if experiment else []),
                 f"-D{kernel}={symbol}", "-c",
                 source / "kernels" / f"{kernel}.c", "-o", obj])
            objects.append(obj)
            objdump = Path(str(args.gcc.resolve()).removesuffix("gcc") + "objdump")
            (out / f"{kernel}.{tune}.asm").write_text(
                subprocess.check_output([objdump, "-d", obj], text=True))
    if experiment or args.suite or args.layout:
        order = TUNES[args.layout:] + TUNES[:args.layout]
        objects = [out / f"{kernel}.{tune}.o" for kernel in kernels for tune in order]
    harness = out / "harness.o"
    defines = ["-DBENCH_SUITE"] if args.suite else []
    run([args.runtime_gcc.resolve(), *common, "-O2", "-mtune=rocket", *defines,
         "-c", source / harness_name, "-o", harness])
    binary = out / "timing.riscv"
    run([args.runtime_gcc.resolve(), *common, f"-specs={args.runtime_specs}", harness,
         *objects, "-o", binary])
    nm = Path(str(args.runtime_gcc.resolve()).removesuffix("gcc") + "nm")
    symbols = subprocess.check_output([nm, "-n", binary], text=True)
    addresses = {}
    for line in symbols.splitlines():
        fields = line.split()
        if len(fields) == 3 and any(fields[2] == f"{k}_{t.replace('-', '_')}" for k in kernels for t in TUNES):
            addresses[fields[2]] = fields[0]
    if len(addresses) != len(kernels) * len(TUNES):
        raise ValueError("Linked binary does not contain every kernel variant")
    max_cycles = experiment.get("max_cycles", 10000000) if experiment else (30000000 if args.suite else 10000000)
    command = [str(args.simulator.resolve()), "+permissive", f"+max-cycles={max_cycles}",
               "+verilator+seed+1", f"+loadmem={binary}"]
    if args.dramsim_ini is not None:
        command.extend(["+dramsim", f"+dramsim_ini_dir={args.dramsim_ini.resolve()}"])
    command.extend(["+permissive-off", str(binary)])
    metadata = {
        "gcc": subprocess.check_output([args.gcc.resolve(), "--version"], text=True).splitlines()[0],
        "runtime_gcc": subprocess.check_output([args.runtime_gcc.resolve(), "--version"], text=True).splitlines()[0],
        "simulator": str(args.simulator.resolve()), "simulator_sha256": file_hash(args.simulator),
        "binary_sha256": file_hash(binary), "opt": args.opt,
        "suite": args.suite, "experiment": experiment["name"] if experiment else "original",
        "layout": args.layout, "kernel_addresses": addresses,
        "source_sha256": {p.name: file_hash(p) for p in [source / harness_name, Path(__file__),
            *([source / experiment["driver"]] if experiment else []),
            *([source / p for p in experiment.get("extra_sources", [])] if experiment else []),
            *(source / "kernels" / f"{k}.c" for k in kernels)]},
        "compile_commands": commands, "simulation_command": command,
        "notes": "Warm-cache, one binary, rotated tune order; cycles include common call/loop/counter overhead. No wall-clock speedup claims.",
    }
    (out / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    # Local hardware simulation may require shared libraries from Chipyard.
    with (out / "simulation.log").open("w") as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                       stdin=subprocess.DEVNULL, check=True, timeout=args.timeout, env=os.environ.copy())
    parse = experiment["parse"] if experiment else (parse_suite_results if args.suite else parse_results)
    summary = parse((out / "simulation.log").read_text())
    (out / "results.json").write_text(json.dumps(summary, indent=2) + "\n")
    report = [f"Simulator: {args.simulator.name}", f"Optimization: -{args.opt}",
              (experiment["description"] if experiment else
               "Warm-cache cycles: 2 calls, 3 samples; 3 sizes, 4 input patterns."
               if args.suite else "Warm-cache cycles for 8 calls of 128 elements; median of 6 samples."),
              f"Code layout: {args.layout}",
              "kernel tune median_cycles min max speedup_vs_rocket"]
    for row in summary:
        case = (f"n={row['n']} streams={row['streams']} " if experiment else
                f"{row['n']} {row['pattern']} " if args.suite else "")
        report.append(f"{case}{row['kernel']} {row['tune']} {row['median_cycles']:g} "
                      f"{row['min_cycles']} {row['max_cycles']} {row['speedup']:.4f}x")
    (out / "REPORT.txt").write_text("\n".join(report) + "\n")
    print("\n".join(report))


if __name__ == "__main__":
    main()
