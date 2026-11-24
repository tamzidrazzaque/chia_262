#!/usr/bin/env python3
"""Kernel cycle table from Verilator logs.  [verilator-megaboom-rtl]

  table.py results/ base A B C [D E]          (unaligned ELFs)
  table.py results/ A-al B-al C-al ...        (4 KiB-aligned kernel functions)
Prints min-of-reps cycles (and rep list), instret, checksum agreement, and
relative change vs the first non-base variant.
"""
import re, sys, os

LINE = re.compile(r"RT k=(\S+) cyc=([\d,]+) ins=([\d,]+) sum=([0-9a-f]+)")


def load(path):
    out = {}
    for line in open(path, errors="replace"):
        m = LINE.search(line)
        if m:
            out[m.group(1)] = ([int(x) for x in m.group(2).split(",")], int(m.group(3).split(",")[0]), m.group(4))
    return out


def main():
    d, vs = sys.argv[1], sys.argv[2:]
    data = {v: load(os.path.join(d, v + ".log")) for v in vs}
    ref = next((v for v in vs if not v.startswith("base")), vs[0])
    names = list(next(iter(data.values())).keys())
    print("| kernel | " + " | ".join(f"{v} cyc (reps) / ins" for v in vs) + " | " +
          " | ".join(f"{v} vs {ref}" for v in vs if v != ref) + " | sums |")
    print("|---" * (2 + len(vs) + len([v for v in vs if v != ref])) + "|")
    for k in names:
        cells, rel = [], []
        sums = {data[v][k][2] for v in vs if k in data[v]}
        for v in vs:
            c, i, s = data[v][k]
            cells.append(f"{min(c)} ({','.join(map(str, c))}) / {i}")
        r = min(data[ref][k][0])
        for v in vs:
            if v != ref:
                rel.append(f"{100.0 * (min(data[v][k][0]) - r) / r:+.1f}%")
        print(f"| {k} | " + " | ".join(cells) + " | " + " | ".join(rel) + f" | {'agree' if len(sums) == 1 else 'MISMATCH'} |")


if __name__ == "__main__":
    main()
