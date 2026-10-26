"""Compare opcode choices in privately built SPEC CPU2017 object files.

Output contains function names and aggregate counts, not benchmark sources or
disassembly. Opcode equality alone does not imply equal scheduling or semantics.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import subprocess
from pathlib import Path


TUNES = ("rocket", "generic-ooo", "xiangshan-nanhu")
HEADER = re.compile(r"^[0-9a-f]+ <(.+)>:$")
INSTRUCTION = re.compile(r"^\s*[0-9a-f]+:\s+([A-Za-z][A-Za-z0-9._]*)\b")


def parse_functions(nm_output: str, disassembly: str) -> dict[str, dict]:
    """Return the size and opcode sequence of each defined text symbol."""
    sizes = {}
    for line in nm_output.splitlines():
        fields = line.split()
        if len(fields) == 4 and fields[1] in ("T", "t", "W", "w"):
            sizes[fields[0]] = int(fields[3], 16)
    opcodes = {name: [] for name in sizes}
    current = None
    for line in disassembly.splitlines():
        if line.startswith("Disassembly of section "):
            current = None
        header = HEADER.match(line)
        if header:
            if header[1] in sizes:
                current = header[1]
            elif not header[1].startswith(".L"):
                current = None
            continue
        instruction = INSTRUCTION.match(line)
        if instruction and current is not None:
            opcodes[current].append(instruction[1])
    return {name: {"bytes": size, "opcodes": opcodes[name]}
            for name, size in sizes.items()}


def compare(baseline: dict, candidate: dict) -> list[dict]:
    """Summarize changed functions by object/symbol across two tunes."""
    rows = []
    for obj, reference in baseline.items():
        if obj not in candidate:
            rows.append({"object": obj, "status": "missing object"})
            continue
        for symbol, base in reference.items():
            other = candidate[obj].get(symbol)
            if other is None:
                rows.append({"object": obj, "symbol": symbol, "status": "missing symbol"})
                continue
            first, second = base["opcodes"], other["opcodes"]
            if first == second and base["bytes"] == other["bytes"]:
                continue
            minus = collections.Counter(first) - collections.Counter(second)
            plus = collections.Counter(second) - collections.Counter(first)
            if minus or plus:
                kind = "opcode mix changed"
            elif first != second:
                kind = "opcode order changed"
            else:
                kind = "same opcode order; encoding size changed"
            rows.append({
                "object": obj, "symbol": symbol, "rocket_bytes": base["bytes"],
                "tuned_bytes": other["bytes"], "rocket_instructions": len(first),
                "tuned_instructions": len(second),
                "opcode_change": kind,
                "removed_opcodes": dict(sorted(minus.items())),
                "added_opcodes": dict(sorted(plus.items())),
            })
    return sorted(rows, key=lambda row: (
        -sum(row.get("removed_opcodes", {}).values())
        -sum(row.get("added_opcodes", {}).values()),
        -abs(row.get("rocket_bytes", 0) - row.get("tuned_bytes", 0)),
        row["object"], row.get("symbol", ""),
    ))


def collect(build_dir: Path, nm: Path, objdump: Path) -> dict:
    """Inspect every object once with nm and objdump."""
    objects = {}
    for obj in sorted(build_dir.rglob("*.o")):
        names = subprocess.check_output([nm, "-S", "-P", "--defined-only", obj], text=True)
        assembly = subprocess.check_output([objdump, "-d", "--no-show-raw-insn", obj], text=True)
        objects[str(obj.relative_to(build_dir))] = parse_functions(names, assembly)
    if not objects:
        raise ValueError(f"No object files found in {build_dir}")
    return objects


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec-dir", type=Path, required=True)
    parser.add_argument("--gcc-root", type=Path, required=True)
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[56]\d{2}\.[A-Za-z0-9_]+_[rs]", args.benchmark):
        parser.error("Expected a SPEC CPU2017 benchmark name")
    prefix = args.gcc_root.resolve() / "bin/riscv64-unknown-linux-gnu-"
    nm = Path(str(prefix) + "nm")
    objdump = Path(str(prefix) + "objdump")
    base = args.spec_dir.resolve() / "benchspec/CPU" / args.benchmark / "build"
    by_tune = {}
    for tune in TUNES:
        label = f"riscv_{tune.replace('-', '_')}-64"
        by_tune[tune] = collect(base / f"build_base_{label}.0000", nm, objdump)
    report = {
        "benchmark": args.benchmark,
        "object_count": {tune: len(objects) for tune, objects in by_tune.items()},
        "function_count": {tune: sum(map(len, objects.values())) for tune, objects in by_tune.items()},
        "comparisons": {tune: compare(by_tune["rocket"], by_tune[tune])
                        for tune in TUNES[1:]},
    }
    out = args.out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")
    for tune, rows in report["comparisons"].items():
        mix = sum(row.get("opcode_change") == "opcode mix changed" for row in rows)
        print(f"{args.benchmark} {tune}: {len(rows)} changed functions; {mix} opcode mixes; {out}")


if __name__ == "__main__":
    main()
