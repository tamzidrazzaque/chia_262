"""Screen real SPEC workloads locally without FireSim or F2.

Builds and validates roles 1 and 2 with the existing private SPEC installation,
then audits the role-2 ELF for RVV instructions. QEMU/SPEC correctness and
static RVV evidence are gates only; no host or QEMU time is a performance result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

from spec_vector_baseline import ROLES, sha256


RVV_RE = re.compile(
    r"\b(v(?:set|le|se|l|s|add|sub|mul|fmul|fadd|fsub|fmacc|slide|red|and|or|xor|"
    r"merge|mv|compress|first|cpop|class|f(?:eq|lt|le|min|max|sqrt|div)|wad|wmul|"
    r"sll|srl|sra|nsrl|nsra|clip|adc|sbc|ms(?:gt|lt|le|ge)|madc|msbc)"
    r"(?:\.|$))"
)


def find_elf(spec_dir: Path, benchmark: str, label: str) -> Path:
    """Find the newest executable in the private SPEC run directory."""
    root = spec_dir / "benchspec/CPU" / benchmark / "run"
    candidates = [
        path for path in root.glob(f"run_base_*_{label}-64.*/**/*")
        if path.is_file() and path.stat().st_mode & 0o111
    ]
    if not candidates:
        raise FileNotFoundError(f"no executable found under {root} for {label}")
    return max(candidates, key=lambda path: path.stat().st_mtime_ns)


def audit_rvv(objdump: Path, elf: Path) -> dict:
    """Disassemble one ELF and require actual RVV mnemonics."""
    text = subprocess.check_output([str(objdump), "-d", str(elf)], text=True,
                                   errors="replace")
    mnemonics = sorted({match.group(1) for match in RVV_RE.finditer(text)})
    return {"elf": str(elf), "elf_sha256": sha256(elf),
            "rvv_instruction_count": len(RVV_RE.findall(text)),
            "rvv_mnemonics": mnemonics, "contains_rvv": bool(mnemonics)}


def run_role(args: argparse.Namespace, role: str, out: Path) -> None:
    """Build or validate one role through the existing private SPEC driver."""
    script = Path(__file__).with_name("spec_vector_baseline.py")
    command = [sys.executable, str(script), "--spec-dir", str(args.spec_dir),
               "--gcc-root", str(args.gcc_root), "--speckle", str(args.speckle),
               "--qemu", str(args.qemu), "--out", str(out), "--benchmark",
               args.benchmark, "--size", args.size, "--role", role]
    for action in ("build", "validate"):
        result = subprocess.run([*command, "--action", action], check=False)
        if result.returncode:
            raise RuntimeError(f"{role} {action} failed with exit {result.returncode}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec-dir", type=Path, required=True)
    parser.add_argument("--gcc-root", type=Path, required=True)
    parser.add_argument("--speckle", type=Path, required=True)
    parser.add_argument("--qemu", type=Path, required=True)
    parser.add_argument("--objdump", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--size", choices=("test", "train"), default="test")
    args = parser.parse_args()
    if not re.fullmatch(r"[56]\d{2}\.[A-Za-z0-9_]+_[rs]", args.benchmark):
        parser.error("--benchmark must be a SPEC CPU2017 benchmark name")
    for path in (args.spec_dir, args.gcc_root, args.speckle, args.qemu, args.objdump):
        if not path.exists():
            parser.error(f"missing prerequisite: {path}")
    args.out.mkdir(mode=0o700, parents=True, exist_ok=True)
    roles = ("1-scalar", "2-generic-vector")
    try:
        for role in roles:
            run_role(args, role, args.out)
        role2 = find_elf(args.spec_dir, args.benchmark, "saturn_role2_generic_vector")
        audit = audit_rvv(args.objdump, role2)
        if not audit["contains_rvv"]:
            raise RuntimeError("role 2 passed SPEC but emitted no RVV instructions")
        result = {
            "stage": "local-spec-screen",
            "f2_launched": False,
            "benchmark": args.benchmark,
            "size": args.size,
            "roles": list(roles),
            "role2_rvv_audit": audit,
            "target_performance_result": False,
            "next_gate": "private FireSim staging and native output comparison",
        }
        result_path = args.out / f"{args.benchmark}-{args.size}-screen.json"
        result_path.write_text(json.dumps(result, indent=2) + "\n")
        print(result_path)
        return 0
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"screen rejected: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
