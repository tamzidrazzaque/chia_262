#!/usr/bin/env python3
"""Correctness harness for boom_div_select (run under QEMU user mode).

Writes shard_<i>.c: for each (type, divisor, op) a noinline function
f(x) = x OP D (constant: the plugin rewrites it) and a reference
r(x) = x OP vd, vd a volatile global holding D (hardware div, never touched
by the plugin).  main() checks f == r on edge dividends + N random ones.
"""
import os
import random
import sys

R = random.Random(20261123)
TYPES = {  # name: (ctype, bits, signed)
    "u64": ("unsigned long", 64, False), "s64": ("long", 64, True),
    "u32": ("unsigned int", 32, False), "s32": ("int", 32, True),
    "u16": ("unsigned short", 16, False), "s16": ("short", 16, True),
    "u8": ("unsigned char", 8, False), "s8": ("signed char", 8, True),
}


def divisors(bits, sgn):
    top = (1 << (bits - 1)) - 1 if sgn else (1 << bits) - 1
    ds = set(range(2, 301))
    for k in range(2, bits + 1):
        for e in (-1, 0, 1):
            ds.add((1 << k) + e)
    ds |= {1000, 4000, 10007, 1000003, 10 ** 9 + 7, 0x7fffffff, 0x80000001, 6700417, 641,
           (1 << 63) - 1, (1 << 63) - 25, 3 ** 39}
    for b in range(3, bits + 1):
        for _ in range(3):
            ds.add(R.randrange(1 << (b - 1), 1 << b))
    ds = {d for d in ds if 2 <= d <= top}
    if sgn:
        ds |= {-d for d in list(ds)}
        ds.add(-(1 << (bits - 1)))
    return sorted(ds)


def lit(v, t):
    ct, bits, sgn = TYPES[t]
    if sgn and v == -(1 << (bits - 1)):
        return f"(({ct})(-{(1 << (bits - 1)) - 1}LL - 1))"
    return f"(({ct}){v}{'ULL' if not sgn else 'LL'})"


def main(outdir, nshards):
    os.makedirs(outdir, exist_ok=True)
    items = []
    for t in TYPES:
        _, bits, sgn = TYPES[t]
        for d in divisors(bits, sgn):
            for op in ("/", "%"):
                items.append((t, d, op))
    R.shuffle(items)
    shards = [items[i::nshards] for i in range(nshards)]
    for si, its in enumerate(shards):
        L = ['#include "driver.inc"']
        tab = []
        for j, (t, d, op) in enumerate(its):
            ct = TYPES[t][0]
            L.append(f"__attribute__((noinline)) {ct} f{j}({ct} x) {{ return x {op} {lit(d, t)}; }}")
            L.append(f"static volatile {ct} v{j} = {lit(d, t)};")
            L.append(f"__attribute__((noinline)) {ct} r{j}({ct} x) {{ return x {op} v{j}; }}")
            tab.append(f'  T_{t}(f{j}, r{j}, {lit(d, t)}, "{t} {op} {d}"),')
            # range-limited dividend (non-negative / below half range): exercises the
            # plugin's other-signedness sequence (seq_alt_sign) and range-based decisions
            bits = TYPES[t][1]
            m = (1 << (bits - 1)) - 1
            L.append(f"__attribute__((noinline)) {ct} g{j}({ct} x) {{ x &= ({ct}){m}ULL; return x {op} {lit(d, t)}; }}")
            L.append(f"__attribute__((noinline)) {ct} h{j}({ct} x) {{ x &= ({ct}){m}ULL; return x {op} v{j}; }}")
            tab.append(f'  T_{t}(g{j}, h{j}, {lit(d, t)}, "masked {t} {op} {d}"),')
        L.append("static const struct ent E[] = {")
        L += tab
        L.append("};")
        L.append("int main(int argc, char **argv) { return run(E, sizeof E / sizeof E[0], argc > 1 ? atol(argv[1]) : 10000); }")
        open(os.path.join(outdir, f"shard_{si}.c"), "w").write("\n".join(L) + "\n")
    print(f"{len(items)} functions in {nshards} shards")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]))
