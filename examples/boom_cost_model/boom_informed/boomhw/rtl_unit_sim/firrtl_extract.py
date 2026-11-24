#!/usr/bin/env python3
"""Cut one module (plus every module it instantiates) out of an elaborated
FIRRTL 3.x circuit and wrap it as a standalone circuit, so a single unit of the
real MegaBOOM design (e.g. rocket MulDiv as instantiated by BOOM's DivUnit) can
be compiled with firtool and simulated with Verilator in isolation.

Usage: firrtl_extract.py <in.fir[.gz]> <TopModule> <out.fir>
"""
import gzip
import re
import sys

MOD_RE = re.compile(r"^  (public )?(module|extmodule|intmodule) (\S+) :")
INST_RE = re.compile(r"^\s+inst \S+ of (\S+)")


def read_modules(path):
    opener = gzip.open if path.endswith(".gz") else open
    mods, cur, header = {}, None, None
    with opener(path, "rt") as f:
        for line in f:
            if header is None:
                header = line.rstrip("\n")          # "FIRRTL version x.y.z"
                continue
            m = MOD_RE.match(line)
            if m:
                cur = m.group(3)
                mods[cur] = [line]
                continue
            if cur is not None:
                if line.startswith("  ") or line.strip() == "":
                    mods[cur].append(line)
                else:
                    cur = None
    return header, mods


def closure(mods, top):
    seen, order, stack = set(), [], [top]
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        if name not in mods:
            raise KeyError(f"module {name} not found in circuit")
        seen.add(name)
        order.append(name)
        for line in mods[name]:
            m = INST_RE.match(line)
            if m:
                stack.append(m.group(1))
    return order


def extract(path, top):
    header, mods = read_modules(path)
    names = closure(mods, top)
    out = [header, f"circuit {top} :"]
    for name in names:
        body = list(mods[name])
        if name == top:
            body[0] = re.sub(r"^  public module ", "  module ", body[0])  # FIRRTL 3.x: top = circuit name
            # abstract Reset cannot be inferred at a top-level port: make it synchronous UInt<1>
            body = [re.sub(r"^(    input reset : )Reset\b", r"\1UInt<1>", l) for l in body]
        out.extend(l.rstrip("\n") for l in body)
    return "\n".join(out) + "\n", names


def main(argv):
    if len(argv) != 4:
        print(__doc__)
        return 2
    text, names = extract(argv[1], argv[2])
    with open(argv[3], "w") as f:
        f.write(text)
    print(f"extracted {argv[2]} with {len(names)} modules: {', '.join(names)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
