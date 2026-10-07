"""Extract GCC RISC-V cost models and compare the assembly they produce.

The models that matter for a first BOOM experiment live in the GCC RISC-V
backend (not in Chipyard):

  gcc/config/riscv/riscv-cores.def   which -mtune/-mcpu name uses which model
  gcc/config/riscv/riscv.cc          riscv_tune_param cost tables
  gcc/config/riscv/xiangshan.md      Xiangshan pipeline reservations

-mtune= selects the cost model and the scheduling automaton.
-mcpu= does that and also selects the core's default -march.

Usage:
  python compare_cost_models.py --gcc-src /path/to/gcc/gcc/config/riscv --out /path/to/out
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path


# Scalar cost tables to put side by side. Kunminghu's TUNE_INFO is the
# generic out-of-order table; Nanhu has its own.
FOCUS = (
    "generic",
    "rocket",
    "generic-ooo",
    "xiangshan-nanhu",
    "xiangshan-kunminghu",
)

# Same -march for every tune, so a diff is the cost model and not a new ISA.
MARCH = "rv64gc"
OPT_LEVELS = ("-O2", "-O3")
# GCC 13 accepts these. They are the models we can actually compile with
# until a GCC 14+ toolchain that knows Xiangshan is on the path.
LOCAL_TUNES = ("sifive-7-series", "thead-c906", "size")

# Field order of struct riscv_tune_param in gcc/config/riscv/riscv.cc.
# Initializers omit the tail and C++ defaults apply.
TUNE_FIELDS = (
    "fp_add",
    "fp_mul",
    "fp_div",
    "int_mul",
    "int_div",
    "issue_rate",
    "branch_cost",
    "memory_cost",
    "fmv_cost",
    "slow_unaligned_access",
    "vector_unaligned_access",
    "use_divmod_expansion",
    "overlap_op_by_pieces",
    "use_zero_stride_load",
    "speculative_sched_vsetvl",
    "fusible_ops",
    "vec_costs",
    "function_align",
    "jump_align",
    "loop_align",
    "prefer_agnostic",
    "int_reassoc_width",
    "fp_reassoc_width",
    "vec_reassoc_width",
    "small_loop_unroll_ninsns",
    "small_loop_unroll_factor",
    "autoprefetcher_model",
    "scalar_units",
    "vector_units",
)
TUNE_DEFAULTS = {
    "int_reassoc_width": "1",
    "fp_reassoc_width": "1",
    "vec_reassoc_width": "1",
    "small_loop_unroll_ninsns": "4",
    "small_loop_unroll_factor": "2",
    "autoprefetcher_model": "AUTOPREFETCHER_OFF",
    "scalar_units": "0",
    "vector_units": "0",
}


def _brace_body(text: str, open_at: int) -> str:
    depth = 0
    for i in range(open_at, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[open_at + 1 : i]
    raise ValueError("unbalanced brace")


def _split_top(text: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in text:
        if ch in "{(":
            depth += 1
        elif ch in "})":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return [p for p in parts if p and not p.startswith("#")]


def _clean(value: str) -> str:
    value = re.sub(r"/\*.*?\*/", "", value, flags=re.S)
    return re.sub(r"\s+", " ", value).strip().rstrip(",")


def parse_tunes(cores_def: str) -> list[dict]:
    tunes = []
    for name, pipeline, info in re.findall(
        r'RISCV_TUNE\(\s*"([^"]+)"\s*,\s*([A-Za-z0-9_]+)\s*,\s*([A-Za-z0-9_]+)\s*\)',
        cores_def,
    ):
        tunes.append({"name": name, "pipeline": pipeline, "tune_info": info})
    if not tunes:
        raise ValueError("no RISCV_TUNE entries in riscv-cores.def")
    return tunes


def parse_cores(cores_def: str) -> list[dict]:
    cores = []
    for body in re.findall(r"RISCV_CORE\((.*?)\)\s*(?:\n|$)", cores_def, flags=re.S):
        body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
        strings = re.findall(r'"([^"]*)"', body)
        if len(strings) < 3:
            continue
        # ARCH is several adjacent string literals; MICRO_ARCH is the last one.
        cores.append({
            "name": strings[0],
            "arch": "".join(strings[1:-1]),
            "tune": strings[-1],
        })
    return cores


def parse_tune_params(riscv_cc: str) -> dict[str, dict[str, str]]:
    found: dict[str, dict[str, str]] = {}
    for match in re.finditer(
        r"static const struct riscv_tune_param\s+(\w+)\s*=\s*\{",
        riscv_cc,
    ):
        raw_fields = [
            cleaned for cleaned in (
                _clean(p) for p in _split_top(_brace_body(riscv_cc, match.end() - 1))
            )
            if cleaned
        ]
        params = dict(TUNE_DEFAULTS)
        for name, value in zip(TUNE_FIELDS, raw_fields):
            params[name] = value
        if len(raw_fields) > len(TUNE_FIELDS):
            for i, value in enumerate(raw_fields[len(TUNE_FIELDS):], start=len(TUNE_FIELDS)):
                params[f"extra_{i}"] = value
        found[match.group(1)] = params
    if "xiangshan_nanhu_tune_info" not in found or "rocket_tune_info" not in found:
        raise ValueError("riscv.cc is missing Xiangshan or Rocket tune tables")
    return found


def parse_reservations(md_text: str) -> list[dict]:
    return [
        {"name": name, "latency": int(lat)}
        for name, lat in re.findall(
            r'\(define_insn_reservation\s+"([^"]+)"\s+(\d+)',
            md_text,
        )
    ]


def find_gcc() -> str | None:
    env = os.environ.get("RISCV_GCC")
    if env:
        return env
    for name in ("riscv64-unknown-elf-gcc", "riscv64-unknown-linux-gnu-gcc"):
        found = shutil.which(name)
        if found:
            return found
    fallback = Path(
        "/scratch/trazzaque/tools/miniforge/envs/rvtools/riscv-tools/bin/riscv64-unknown-elf-gcc"
    )
    return str(fallback) if fallback.is_file() else None


def compiler_tunes(gcc: str) -> tuple[str, list[str], list[str]]:
    version = subprocess.run([gcc, "--version"], check=False, capture_output=True, text=True)
    first = (version.stdout or version.stderr).splitlines()
    help_text = subprocess.run(
        [gcc, "-Q", "--help=target"], check=False, capture_output=True, text=True
    ).stdout

    def arguments(flag: str) -> list[str]:
        match = re.search(
            rf"Known valid arguments for {flag}= option:\s*\n\s*(.+)",
            help_text,
        )
        return match.group(1).split() if match else []

    return (first[0] if first else gcc), arguments("-mtune"), arguments("-mcpu")


def _normalize_asm(text: str) -> str:
    kept = []
    for line in text.splitlines():
        code = line.split("#", 1)[0].strip()
        if not code or code.startswith("."):
            continue
        kept.append(code)
    return "\n".join(kept) + ("\n" if kept else "")


def compile_kernels(gcc: str, kernels: list[Path], out_dir: Path, tunes: list[str]) -> list[dict]:
    rows = []
    asm_dir = out_dir / "asm"
    asm_dir.mkdir(parents=True, exist_ok=True)
    for opt in OPT_LEVELS:
        for kernel in kernels:
            by_tune: dict[str, Path] = {}
            for tune in tunes:
                dest = asm_dir / f"{kernel.stem}{opt}.{tune}.s"
                cmd = [gcc, "-S", opt, f"-march={MARCH}", f"-mtune={tune}", kernel.name, "-o", str(dest)]
                proc = subprocess.run(cmd, cwd=kernel.parent, capture_output=True, text=True)
                if proc.returncode != 0:
                    dest.unlink(missing_ok=True)
                    rows.append({
                        "kernel": kernel.name,
                        "opt": opt,
                        "tune": tune,
                        "supported": False,
                        "stderr": (proc.stderr or proc.stdout)[-500:],
                    })
                    continue
                norm = _normalize_asm(dest.read_text())
                norm_path = dest.with_suffix(".norm.s")
                norm_path.write_text(norm)
                by_tune[tune] = norm_path
                rows.append({
                    "kernel": kernel.name,
                    "opt": opt,
                    "tune": tune,
                    "supported": True,
                    "sha256": hashlib.sha256(norm.encode()).hexdigest()[:12],
                    "asm": str(dest),
                })
            for tune, path in by_tune.items():
                if tune == "rocket" or "rocket" not in by_tune:
                    continue
                diff = "".join(difflib.unified_diff(
                    by_tune["rocket"].read_text().splitlines(keepends=True),
                    path.read_text().splitlines(keepends=True),
                    fromfile=f"{kernel.stem}{opt}.rocket",
                    tofile=f"{kernel.stem}{opt}.{tune}",
                ))
                diff_path = out_dir / "diffs" / f"{kernel.stem}{opt}.{tune}.vs-rocket.diff"
                diff_path.parent.mkdir(parents=True, exist_ok=True)
                diff_path.write_text(diff)
                for row in rows:
                    if row["kernel"] == kernel.name and row["opt"] == opt and row["tune"] == tune:
                        row["differs_from_rocket"] = bool(diff.strip())
                        row["diff"] = str(diff_path)
    return rows


def _column(params: dict[str, str], field: str) -> str:
    return params.get(field, "")


def render_report(payload: dict) -> str:
    lines = []
    lines.append("GCC RISC-V cost models for a BOOM comparison")
    lines.append("=" * len(lines[0]))
    lines.append(f"GCC source: {payload['gcc_src']}")
    if payload.get("gcc_rev"):
        lines.append(f"GCC revision: {payload['gcc_rev']}")
    lines.append("")
    lines.append("What to compare")
    lines.append("---------------")
    lines.append("Rocket is the in-order baseline. generic-ooo is GCC's stock out-of-order")
    lines.append("model. Xiangshan is the upstream out-of-order model closest to BOOM.")
    lines.append("Nanhu has its own cost table. Kunminghu's table is generic_ooo_tune_info;")
    lines.append("its pipeline automaton is still xiangshan.md.")
    lines.append("")
    lines.append("Use -mtune to change only the cost model. -mcpu also changes -march,")
    lines.append("so it mixes ISA extensions into the comparison.")
    lines.append("")
    lines.append("Tune names")
    lines.append("----------")
    by_name = {t["name"]: t for t in payload["tunes"]}
    for name in FOCUS:
        tune = by_name[name]
        lines.append(f"  -mtune={name:<24} pipeline={tune['pipeline']:<12} table={tune['tune_info']}")
    lines.append("")
    lines.append("Xiangshan -mcpu default architectures")
    lines.append("-------------------------------------")
    for core in payload["cores"]:
        if core["name"].startswith("xiangshan"):
            lines.append(f"  -mcpu={core['name']}")
            lines.append(f"    tune={core['tune']}")
            lines.append(f"    arch={core['arch']}")
    lines.append("")
    lines.append("Cost tables")
    lines.append("-----------")
    lines.append("Values are the C initializers. A field omitted from a table uses the")
    lines.append("default recorded below. COSTS_N_INSNS(N) is GCC's per-instruction cost unit.")
    focus_params = []
    for name in FOCUS:
        info = by_name[name]["tune_info"]
        focus_params.append((name, payload["params"][info]))
    differing = [f for f in TUNE_FIELDS if len({_column(p, f) for _, p in focus_params}) > 1]
    lines.append("")
    lines.append("Fields that are not the same across these five models:")
    for field in differing:
        lines.append(f"  {field}")
        for name, params in focus_params:
            lines.append(f"    {name:<24} {_column(params, field)}")
    lines.append("")
    lines.append("Full table for each model:")
    for name, params in focus_params:
        lines.append(f"  [{name}]")
        for field in TUNE_FIELDS:
            lines.append(f"    {field:<28} {_column(params, field)}")
    lines.append("")
    xs = payload.get("xiangshan_pipeline") or {}
    if xs.get("reservations"):
        lines.append("Xiangshan pipeline reservations (latency in cycles)")
        lines.append("----------------------------------------------------")
        lines.append("From xiangshan.md. Nanhu is described there as a 6-issue out-of-order core")
        lines.append("(1 jmp, 4 alu, 2 mdu, 4 fma, 2 fmisc, 2 ld, 2 st).")
        for item in xs["reservations"]:
            lines.append(f"  {item['name']:<28} {item['latency']}")
        lines.append("")
    cc = payload.get("compiler")
    lines.append("Codegen on this machine")
    lines.append("-----------------------")
    if not cc:
        lines.append("No riscv64 gcc was found. Set RISCV_GCC and rerun.")
    else:
        lines.append(f"Compiler: {cc['version']}")
        lines.append(f"Command shape: riscv64-unknown-elf-gcc -S -O2 -march={MARCH} -mtune=<model>")
        supported = []
        for row in cc["results"]:
            if row["supported"] and row["tune"] not in supported:
                supported.append(row["tune"])
        missing = [name for name in FOCUS if name not in supported]
        lines.append("Produced assembly for: " + (", ".join(supported) if supported else "(none)"))
        if missing:
            lines.append("Rejected by this compiler: " + ", ".join(missing))
            lines.append("Those names are in current GCC source. This binary is older, so their")
            lines.append("tables above are from the source checkout, and the assembly comparison")
            lines.append("uses the models this binary accepts (including SiFive 7, C906, and size).")
        lines.append("")
        lines.append(f"{'kernel':<16} {'opt':<6} {'tune':<24} {'vs rocket'}")
        for row in cc["results"]:
            if not row["supported"]:
                verdict = "unsupported"
            elif row["tune"] == "rocket":
                verdict = "baseline"
            elif row.get("differs_from_rocket"):
                verdict = "DIFFERS"
            else:
                verdict = "same"
            lines.append(f"{row['kernel']:<16} {row['opt']:<6} {row['tune']:<24} {verdict}")
        lines.append("")
        lines.append("Assembly is under asm/. Diffs against -mtune=rocket are under diffs/.")
    lines.append("")
    lines.append("Flags to carry into CHIA")
    lines.append("------------------------")
    lines.append("Small kernels, cost model only (same ISA):")
    for name in FOCUS:
        lines.append(f"  -march={MARCH} -mtune={name}")
    lines.append("Whole-core defaults, including that core's extensions:")
    lines.append("  -mcpu=xiangshan-nanhu")
    lines.append("  -mcpu=xiangshan-kunminghu")
    lines.append("")
    lines.append("On a CHIA cluster those strings are spec_flags in")
    lines.append("examples/firesim_spec/spec_eval.py and examples/spec_build/spec_sw_build_loop.py.")
    lines.append("The inner loop is these kernels. The outer loop is SPEC on FireSim,")
    lines.append("recompiled once per flag set, on a BOOM bitstream and a Rocket bitstream.")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gcc-src", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--kernels", type=Path, default=None)
    args = parser.parse_args()

    src = args.gcc_src
    cores_def = (src / "riscv-cores.def").read_text()
    riscv_cc = (src / "riscv.cc").read_text()
    xiangshan_md = src / "xiangshan.md"
    tunes = parse_tunes(cores_def)
    params = parse_tune_params(riscv_cc)
    by_name = {t["name"]: t for t in tunes}
    missing = [name for name in FOCUS if name not in by_name]
    if missing:
        raise SystemExit(f"riscv-cores.def has no tune entries for: {', '.join(missing)}")
    for name in FOCUS:
        info = by_name[name]["tune_info"]
        if info not in params:
            raise SystemExit(f"riscv.cc has no cost table {info} for -mtune={name}")

    gcc_dir = src
    rev = ""
    for parent in [src, *src.parents]:
        if (parent / ".git").exists():
            proc = subprocess.run(
                ["git", "-C", str(parent), "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, check=False,
            )
            rev = proc.stdout.strip()
            break

    payload = {
        "gcc_src": str(src),
        "gcc_rev": rev,
        "tunes": tunes,
        "cores": [c for c in parse_cores(cores_def) if c["name"].startswith("xiangshan") or c["tune"] in FOCUS],
        "params": {by_name[n]["tune_info"]: params[by_name[n]["tune_info"]] for n in FOCUS},
        "xiangshan_pipeline": {
            "header": "\n".join(xiangshan_md.read_text().splitlines()[:8]) if xiangshan_md.is_file() else "",
            "reservations": parse_reservations(xiangshan_md.read_text()) if xiangshan_md.is_file() else [],
        },
    }

    kernel_dir = args.kernels or (Path(__file__).resolve().parent / "kernels")
    kernels = sorted(kernel_dir.glob("*.c"))
    gcc = find_gcc()
    if gcc:
        version, mtunes, mcpus = compiler_tunes(gcc)
        tunes = list(FOCUS)
        for extra in LOCAL_TUNES:
            if extra not in tunes and (not mtunes or extra in mtunes):
                tunes.append(extra)
        payload["compiler"] = {
            "path": gcc,
            "version": version,
            "accepted_mtune": mtunes,
            "accepted_mcpu": mcpus,
            "results": compile_kernels(gcc, kernels, args.out, tunes),
        }
    else:
        payload["compiler"] = None

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "cost_models.json").write_text(json.dumps(payload, indent=2) + "\n")
    report = render_report(payload)
    (args.out / "REPORT.txt").write_text(report)
    print(report)
    print(f"Wrote {args.out / 'REPORT.txt'}")


if __name__ == "__main__":
    main()
