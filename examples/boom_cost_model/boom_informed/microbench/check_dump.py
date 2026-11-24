#!/usr/bin/env python3
"""Static check: for every kernel, the mnemonic histogram of the linked binary's
timed region (between 'rdcycle a7' and 'rdcycle a0') equals the generator IR.
Catches assembler/linker surprises (pseudo-op expansion, compression, relaxation).
  python3 check_dump.py build/   (needs build/*.dump from 'make')"""
import collections
import glob
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "gen"))


def regions(dump):
    out, cur, name = {}, None, None
    for line in open(dump):
        m = re.match(r"^[0-9a-f]+ <k_(\S+)>:", line)
        if m:
            name, cur = m.group(1), None
            continue
        m = re.match(r"^\s+[0-9a-f]+:\s+[0-9a-f]+\s+(\S+)\s*(.*)$", line)
        if not m or name is None:
            continue
        op, args = m.group(1), m.group(2)
        if op == "rdcycle" and args.startswith("a7"):
            cur = collections.Counter()
            continue
        if op == "rdcycle" and args.startswith("a0") and cur is not None:
            out[name] = cur
            cur = None
            continue
        if cur is not None:
            cur[op] += 1
    return out


def ir_hist(asm_path):
    hist, cur, name = {}, None, None
    for line in open(asm_path):
        m = re.match(r"^k_(\S+):$", line.strip())
        if m:
            name = m.group(1)
            continue
        s = line.strip()
        if s.startswith("rdcycle\ta7"):
            cur = collections.Counter()
        elif s.startswith("rdcycle\ta0"):
            hist[name] = cur
            cur = None
        elif cur is not None and s and not s.endswith(":"):
            op = s.split()[0]
            cur[op] += 1
    return hist


def main(bdir):
    bad = total = 0
    for dump in sorted(glob.glob(os.path.join(bdir, "mb_*.dump"))):
        g = os.path.basename(dump)[3:-5]
        got = regions(dump)
        want = ir_hist(os.path.join(bdir, f"{g}_kernels.S"))
        for k, w in want.items():
            total += 1
            # 'li t,-1' assembles to 'li' (addi) on objdump; same mnemonic
            if got.get(k) != w:
                bad += 1
                print(f"MISMATCH {g}/{k}: ir={dict(w)} bin={dict(got.get(k, {}))}")
    print(f"check_dump: {total - bad}/{total} kernels have identical timed-region mnemonic histograms")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "build"))
