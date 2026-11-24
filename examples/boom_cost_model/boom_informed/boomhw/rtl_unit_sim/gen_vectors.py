#!/usr/bin/env python3
"""Deterministic operand vectors for the MulDiv unit-RTL sweep.

fn codes (rocket ALU.scala): 4=DIV 5=DIVU 6=REM 7=REMU; dw 1=64-bit, 0=32-bit (W).
Sweep: every (dividend MSB, divisor MSB) pair for divu/64, a signed/W subset,
plus edge cases and a seeded random set.
"""
import random
import sys

M64 = (1 << 64) - 1


def val_with_msb(rng, msb):
    if msb < 0:
        return 0
    lo = rng.getrandbits(msb) if msb > 0 else 0
    return (1 << msb) | lo


def vectors(seed=262):
    rng = random.Random(seed)
    out = []
    # 1. full MSB grid, unsigned 64-bit divide
    for d in range(64):
        for v in range(64):
            out.append((5, 1, val_with_msb(rng, d), val_with_msb(rng, v)))
    # 2. zero dividend
    for v in range(64):
        out.append((5, 1, 0, val_with_msb(rng, v)))
    # 3. signed / remainder / W forms on a coarser grid, all sign combinations
    for fn in (4, 5, 6, 7):
        for dw in (1, 0):
            width = 64 if dw else 32
            for d in range(0, width - 1, 3):
                for v in range(0, width - 1, 5):
                    for sa in (1, -1):
                        for sb in (1, -1):
                            a = val_with_msb(rng, d) * sa
                            b = val_with_msb(rng, v) * sb
                            if dw == 0:
                                # upper 32 bits random garbage: W ops must ignore them
                                a = (rng.getrandbits(32) << 32) | (a & 0xFFFFFFFF)
                                b = (rng.getrandbits(32) << 32) | (b & 0xFFFFFFFF)
                            out.append((fn, dw, a & M64, b & M64))
    # 4. edge cases
    edges = [0, 1, 2, 3, 7, 10, 13, 100, 4000, M64, 1 << 63, (1 << 63) - 1,
             0xFFFFFFFF, 0x80000000, 0x7FFFFFFF]
    for fn in (4, 5, 6, 7):
        for dw in (1, 0):
            for a in edges:
                for b in edges:
                    out.append((fn, dw, a, b))
    # 5. random full-width
    for _ in range(2000):
        out.append((rng.choice((4, 5, 6, 7)), rng.choice((0, 1)),
                    rng.getrandbits(64), rng.getrandbits(rng.randint(1, 64))))
    return out


def main(argv):
    path = argv[1] if len(argv) > 1 else "muldiv_vectors.txt"
    vs = vectors()
    with open(path, "w") as f:
        for fn, dw, a, b in vs:
            f.write(f"{fn} {dw} {a:x} {b:x}\n")
    print(f"wrote {len(vs)} vectors to {path}")


if __name__ == "__main__":
    main(sys.argv)
