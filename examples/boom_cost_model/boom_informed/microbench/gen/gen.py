#!/usr/bin/env python3
"""Generate the MegaBOOM latency/throughput microbenchmark suite.

For each group this writes build/<group>_kernels.S and build/<group>_table.c,
and writes build/manifest.json with every kernel's metadata, its golden
checksum (computed by the independent Python interpreter in rvmodel.py) and
its two PREDICTIONS (boom.md reservations, RTL-source estimate).

Every kernel is a leaf asm function  k_<name>(const u64 *in, u64 *out, u64 *t)
that loads its registers from in[], executes
    rdinstret a6 ; rdcycle a7 ; <body> ; rdcycle a0 ; rdinstret ra
stores t[0]=cycles, t[1]=instret, then stores its live registers to out[].
"""

import argparse
import json
import os
import random
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rvmodel import (Inst, Machine, R3, RI, u64, s64, sext32, s32, tdiv, f2b, b2f,  # noqa: E402
                     schedule, muldiv_core_cycles, DIV_OPS, MASK)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

INT_POOL = [f"s{i}" for i in range(12)] + [f"t{i}" for i in range(7)] + ["a3", "a4", "a5"]
FP_POOL = [f"fs{i}" for i in range(12)] + [f"ft{i}" for i in range(12)] + [f"fa{i}" for i in range(8)]

FAKE_BASE = 0x4000_0000  # interpreter-only base address for data labels


class Alloc:
    def __init__(self):
        self.i = 0
        self.f = 0

    def x(self):
        r = INT_POOL[self.i]
        self.i += 1
        return r

    def fp(self):
        r = FP_POOL[self.f]
        self.f += 1
        return r


class Kernel:
    def __init__(self, name, group, ops, meta):
        self.name, self.group, self.ops, self.meta = name, group, ops, dict(meta)
        self.init = []      # (reg, value | ("sym", label, off))
        self.body = []      # [Inst]
        self.outs = []      # (reg, sub_label | None)
        self.data = []      # labels this kernel references (shared data blocks)


# ----------------------------------------------------------------- data blocks
class Data:
    """Shared data blocks per group: label -> (align, [(size, value|sym)])."""

    def __init__(self):
        self.blocks = {}
        self.base = {}

    def add(self, label, words, align=64):
        if label not in self.blocks:
            self.blocks[label] = (align, words)

    def layout(self):
        addr = FAKE_BASE
        for label, (align, words) in self.blocks.items():
            addr = (addr + align - 1) // align * align
            self.base[label] = addr
            addr += sum(sz for sz, _ in words)

    def resolve(self, v):
        if isinstance(v, tuple):
            return u64(self.base[v[1]] + v[2])
        return u64(v)

    def memory(self):
        mem = {}
        for label, (_, words) in self.blocks.items():
            a = self.base[label]
            for sz, v in words:
                val = self.resolve(v)
                for i in range(sz):
                    mem[a + i] = (val >> (8 * i)) & 0xFF
                a += sz
        return mem

    def asm(self):
        out = []
        for label, (align, words) in self.blocks.items():
            out.append(f"\t.balign {align}")
            out.append(f"{label}:")
            for sz, v in words:
                d = ".dword" if sz == 8 else ".word"
                if isinstance(v, tuple):
                    out.append(f"\t{d} {v[1]}+{v[2]}")
                else:
                    out.append(f"\t{d} {u64(v) & ((1 << (8 * sz)) - 1):#x}")
        return out


def fnv(vals):
    h = 0xcbf29ce484222325
    for v in vals:
        h = ((h ^ u64(v)) * 0x100000001b3) & MASK
    return h


# ------------------------------------------------------------ helpers / rng
RNG = random.Random(20261123)


def rand_range(lo, hi):
    return RNG.randrange(lo, hi)


def is_fp(r):
    return r.startswith("f")


# =================================================================== kernels
VARIANTS = [("c1", 1), ("c2", 2), ("c4", 4), ("c8", 8), ("free", 0)]

# operand classes: (x initial value generator, y, fixup add constant M or None)
#   L = large: dividend msb 62 (64-bit) / 30 (32-bit), divisor 13
#   S = small: dividend in [128,256), divisor 3  -> early-out after few iterations
#   N = negative large dividend (signed ops only): neg_inputs/neg_output steps
def opclass(op, cls):
    w32 = op.endswith("w")
    if op == "add":
        if cls == "L":
            return (lambda: rand_range(1 << 62, 1 << 63)), rand_range(1 << 40, 1 << 62), None
        return (lambda: rand_range(1, 16)), 1, None
    if op in ("mul", "mulw"):
        if cls == "L":
            return (lambda: rand_range(1 << 62, 1 << 64)), rand_range(1 << 62, 1 << 63) | 1, None
        return (lambda: rand_range(2, 16)), 1, None
    if op in ("mulh", "mulhu"):
        if cls == "L":
            if op == "mulh":
                return (lambda: rand_range(1 << 62, 1 << 63)), rand_range(1 << 62, 1 << 63), 1 << 62
            return (lambda: rand_range(1 << 63, 1 << 64)), rand_range(1 << 62, 1 << 63), 1 << 63
        return (lambda: rand_range(128, 256)), 3, 128
    if op in DIV_OPS:
        if cls == "L":
            if w32:
                return (lambda: rand_range(1 << 30, 1 << 31)), 13, 1 << 30
            return (lambda: rand_range(1 << 62, 1 << 63)), 13, 1 << 62
        if cls == "S":
            return (lambda: rand_range(128, 256)), 3, 128
        if cls == "N":
            if w32:
                return (lambda: sext32(-rand_range(1 << 30, 1 << 31))), 13, sext32(-(1 << 30))
            return (lambda: u64(-rand_range(1 << 62, 1 << 63))), 13, u64(-(1 << 62))
    raise ValueError((op, cls))


def unit_kernel(group, op, cls, var, n, ops):
    k = Kernel(f"{op}_{cls}_{var}", group, ops,
               {"cat": "unit", "op": op, "cls": cls, "variant": var, "chains": n})
    A = Alloc()
    gen_x, y, M = opclass(op, cls)
    ry = A.x()
    k.init.append((ry, y))
    rM = None
    if M is not None and var != "free":
        rM = A.x()
        k.init.append((rM, M))
    k.meta["fixup"] = "add M" if rM else None
    if var == "free":
        srcs = [A.x() for _ in range(4)]
        dsts = [A.x() for _ in range(8)]
        for r in srcs:
            k.init.append((r, gen_x()))
        for r in dsts:
            k.init.append((r, 0))
        for j in range(ops):
            k.body.append(Inst(op, dsts[j % 8], (srcs[j % 4], ry)))
        k.outs = [(r, None) for r in dsts]
    else:
        xs = [A.x() for _ in range(n)]
        for r in xs:
            k.init.append((r, gen_x()))
        for _ in range(ops // n):
            for r in xs:
                k.body.append(Inst(op, r, (r, ry)))
                if rM:
                    k.body.append(Inst("add", r, (r, rM)))
        k.outs = [(r, None) for r in xs]
    return k


def ctl_kernels(group):
    ks = []
    k = Kernel("ctl_empty", group, 1, {"cat": "control", "op": "empty"})
    k.init.append(("s0", 7))
    k.outs = [("s0", None)]
    ks.append(k)
    k = Kernel("ctl_add_dep", group, 128, {"cat": "control", "op": "add", "chains": 1})
    k.init += [("s0", 1), ("s1", 3)]
    k.body = [Inst("add", "s0", ("s0", "s1")) for _ in range(128)]
    k.outs = [("s0", None)]
    ks.append(k)
    return ks


# ------------------------------------------------------------- FP / memory
def fp_kernel(group, op, var, n, ops):
    k = Kernel(f"{op.replace('.', '_')}_{var}", group, ops,
               {"cat": "unit", "op": op, "cls": "-", "variant": var, "chains": n})
    A = Alloc()
    if op == "fdiv.d":
        ry = A.fp(); k.init.append((ry, f2b(1.1)))
        mk = lambda r, s: Inst("fdiv.d", r, (s, ry))
        gx = lambda i: f2b(1.0e10 * (i + 1) + 0.37)
    elif op == "fsqrt.d":
        mk = lambda r, s: Inst("fsqrt.d", r, (s,))
        gx = lambda i: f2b(1.0e300 / (i + 1) + 0.0)
    elif op == "fmadd.d":
        ra = A.fp(); rb = A.fp()
        k.init += [(ra, f2b(0.5)), (rb, f2b(1.25))]
        mk = lambda r, s: Inst("fmadd.d", r, (s, ra, rb))
        gx = lambda i: f2b(3.0 + i)
    if var == "free":
        srcs = [A.fp() for _ in range(4)]
        dsts = [A.fp() for _ in range(8)]
        k.init += [(r, gx(i)) for i, r in enumerate(srcs)] + [(r, 0) for r in dsts]
        k.body = [mk(dsts[j % 8], srcs[j % 4]) for j in range(ops)]
        k.outs = [(r, None) for r in dsts]
    else:
        xs = [A.fp() for _ in range(n)]
        k.init += [(r, gx(i)) for i, r in enumerate(xs)]
        for _ in range(ops // n):
            for r in xs:
                k.body.append(mk(r, r))
        k.outs = [(r, None) for r in xs]
    return k


def ring_block(data, label="ring64", n=64, stride=64):
    perm = list(range(1, n))
    RNG.shuffle(perm)
    order = [0] + perm               # one Hamiltonian cycle through all lines
    nxt = {order[i]: order[(i + 1) % n] for i in range(n)}
    words = []
    for i in range(n):
        words.append((8, ("sym", label, nxt[i] * stride)))
        words += [(8, 0)] * (stride // 8 - 1)
    data.add(label, words, align=64)


def load_kernel(group, data, var, n, ops):
    ring_block(data)
    k = Kernel(f"ld_{var}", group, ops,
               {"cat": "unit", "op": "ld", "cls": "L1hit", "variant": var, "chains": n})
    A = Alloc()
    if var == "free":
        srcs = [A.x() for _ in range(4)]
        dsts = [A.x() for _ in range(8)]
        k.init += [(r, ("sym", "ring64", 64 * (8 * i + 3))) for i, r in enumerate(srcs)]
        k.init += [(r, 0) for r in dsts]
        k.body = [Inst("ld", dsts[j % 8], (srcs[j % 4],), imm=0) for j in range(ops)]
        k.outs = [(r, "ring64") for r in dsts]
    else:
        xs = [A.x() for _ in range(n)]
        k.init += [(r, ("sym", "ring64", 64 * (8 * i))) for i, r in enumerate(xs)]
        for _ in range(ops // n):
            for r in xs:
                k.body.append(Inst("ld", r, (r,), imm=0))
        k.outs = [(r, "ring64") for r in xs]
    return k


# ------------------------------------------------- GCC div-by-constant seqs
_INSN = re.compile(r"^\t([a-z.]+)\t(.*)$")


def parse_gcc(path):
    funcs, cur = {}, None
    for line in open(path):
        line = line.rstrip("\n")
        m = re.match(r"^([A-Za-z_][\w]*):$", line)
        if m:
            cur = m.group(1)
            funcs[cur] = []
            continue
        m = _INSN.match(line)
        if m and cur and not m.group(1).startswith("."):
            op, args = m.group(1), [a.strip() for a in m.group(2).split(",")]
            if op == "ret":
                cur = None
                continue
            funcs[cur].append((op, args))
    return funcs


def _to_inst(op, args):
    if op == "li":
        return Inst("li", args[0], (), imm=u64(int(args[1], 0)))
    if op in RI:
        return Inst(op, args[0], (args[1],), imm=int(args[2], 0))
    if op in R3:
        return Inst(op, args[0], (args[1], args[2]))
    raise ValueError(f"unsupported GCC insn {op} {args}")


def split_const(seq):
    """Split a GCC function body (input/output a0) into hoisted constant
    materialization and the a0-dependent body.  Returns (consts, body) where
    body is a list of (op, rd, [src descriptors], imm): a src descriptor is
    ("x",) for a0, ("t", gccreg) for a body temp, ("c", value) for a constant."""
    state = {"a0": ("x",)}
    body = []
    for op, args in seq:
        ins = _to_inst(op, args)
        src_states = [state.get(r) for r in ins.rs]
        if all(s is not None and s[0] == "c" for s in src_states):
            vals = [s[1] for s in src_states]
            if ins.op == "li":
                v = ins.imm
            elif ins.op in RI:
                v = RI[ins.op](vals[0], ins.imm)
            else:
                v = R3[ins.op](*vals)
            state[ins.rd] = ("c", u64(v))
            continue
        assert all(s is not None for s in src_states), (op, args)
        srcs = []
        for s, r in zip(src_states, ins.rs):
            srcs.append(s if s[0] in ("x", "c") else ("t", r))
        dst = "x" if ins.rd == "a0" else ("t", ins.rd)
        body.append((ins.op, dst, srcs, ins.imm))
        state[ins.rd] = ("x",) if ins.rd == "a0" else ("t", ins.rd)
    assert state["a0"] == ("x",)
    return body


def instantiate(body, xreg, temp_map, const_map):
    out = []
    for op, dst, srcs, imm in body:
        rd = xreg if dst == "x" else temp_map[dst[1]]
        rs = []
        for s in srcs:
            if s[0] == "x":
                rs.append(xreg)
            elif s[0] == "t":
                rs.append(temp_map[s[1]])
            else:
                rs.append(const_map[s[1]])
        out.append(Inst(op, rd, rs, imm=imm))
    return out


def ref_divconst(sig, width, c, x):
    if width == 64:
        if sig:
            return u64(tdiv(s64(x), c))
        return u64(x) // c
    if sig:
        return sext32(tdiv(s32(x), c))
    return sext32((x & 0xFFFFFFFF) // c)


def verify_seq(body, sig, width, c, nrand=20000):
    """Execute the extracted body on edge + random inputs vs reference."""
    temps = sorted({d[1] for _, d, _, _ in body if d != "x"} |
                   {s[1] for _, _, ss, _ in body for s in ss if s[0] == "t"})
    tmap = {t: f"T{t}" for t in temps}
    consts = sorted({s[1] for _, _, ss, _ in body for s in ss if s[0] == "c"})
    cmap = {v: f"C{i}" for i, v in enumerate(consts)}
    prog = instantiate(body, "X", tmap, cmap)
    edges = [0, 1, 2, c if c > 0 else -c, 3, 7, 12, 13, 99, 100, 101, 3999, 4000, 4001]
    if width == 64:
        edges += [MASK, 1 << 63, (1 << 63) - 1, (1 << 63) + 1, u64(-1), u64(-13), u64(-14), u64(-4000)]
    else:
        edges += [0xFFFFFFFF, 1 << 31, (1 << 31) - 1, (1 << 31) + 1]
    xs = [u64(e) for e in edges] + [RNG.getrandbits(64) for _ in range(nrand)]
    for x in xs:
        if width == 32:
            x = sext32(x)  # RV64 ABI: 32-bit args arrive sign-extended
        m = Machine({"X": x, **{r: v for v, r in cmap.items()}})
        m.run(prog)
        got = m.x["X"]
        exp = ref_divconst(sig, width, c, x)
        if width == 32:
            assert got == sext32(got), ("not sign-extended", sig, width, c, hex(x))
        assert got == exp, ("mismatch", sig, width, c, hex(x), hex(got), hex(exp))
    return len(xs)


DIVCONSTS = [3, 7, 10, 13, 100, 4000, -13]


def divconst_kernels(group, gccpath, log):
    funcs = parse_gcc(gccpath)
    ks = []
    for c in DIVCONSTS:
        n = str(c).replace("-", "m")
        for sig, width in ((True, 64), (True, 32), (False, 64), (False, 32)):
            if not sig and c < 0:
                continue
            fname = f"{'s' if sig else 'u'}d{width}_{n}"
            body = split_const(funcs[fname])
            nchk = verify_seq(body, sig, width, c)
            log.append(f"divconst {fname}: {len(body)} body insns {[b[0] for b in body]} verified on {nchk} inputs")
            hwop = {(True, 64): "div", (False, 64): "divu", (True, 32): "divw", (False, 32): "divuw"}[(sig, width)]
            for impl in ("hw", "seq"):
                for var, nch in (("c1", 1), ("c4", 4)):
                    ops = 32
                    k = Kernel(f"dc_{fname}_{impl}_{var}", group, ops,
                               {"cat": "divconst", "fn": fname, "signed": sig, "width": width,
                                "c": c, "impl": impl, "variant": var, "chains": nch,
                                "fixup": "add M", "seq": [b[0] for b in body] if impl == "seq" else [hwop]})
                    A = Alloc()
                    M = (1 << 62) if width == 64 else (1 << 30)
                    rM = A.x(); k.init.append((rM, M))
                    xs = [A.x() for _ in range(nch)]
                    for r in xs:
                        k.init.append((r, rand_range(1 << 62, 1 << 63) if width == 64 else rand_range(1 << 30, 1 << 31)))
                    if impl == "hw":
                        rc = A.x(); k.init.append((rc, u64(c)))
                        for _ in range(ops // nch):
                            for r in xs:
                                k.body.append(Inst(hwop, r, (r, rc)))
                                k.body.append(Inst("add", r, (r, rM)))
                    else:
                        consts = sorted({s[1] for _, _, ss, _ in body for s in ss if s[0] == "c"})
                        cmap = {}
                        for v in consts:
                            rc = A.x(); cmap[v] = rc; k.init.append((rc, v))
                        temps = sorted({d[1] for _, d, _, _ in body if d != "x"} |
                                       {s[1] for _, _, ss, _ in body for s in ss if s[0] == "t"})
                        tmaps = [{t: A.x() for t in temps} for _ in xs]
                        for tm in tmaps:
                            for t in tm.values():
                                k.init.append((t, 0))
                        for _ in range(ops // nch):
                            for r, tm in zip(xs, tmaps):
                                k.body += instantiate(body, r, tm, cmap)
                                k.body.append(Inst("add", r, (r, rM)))
                    k.outs = [(r, None) for r in xs]
                    ks.append(k)
    return ks, funcs


# ------------------------------------------------ div hidden under ALU work
def hide_kernels(group, magic13):
    ks = []
    B = 16
    for K in (8, 16, 32, 64):
        for impl in ("none", "hwdep", "hwind", "muldep", "mulind"):
            k = Kernel(f"hide_K{K}_{impl}", group, B,
                       {"cat": "hide", "K": K, "impl": impl, "blocks": B, "div": "divu by 13 (L class)"})
            A = Alloc()
            ry = A.x(); rM = A.x(); rmg = A.x(); x = A.x(); sink = A.x()
            k.init += [(ry, 13), (rM, 1 << 62), (rmg, magic13), (x, rand_range(1 << 62, 1 << 63)), (sink, 0)]
            xin = [A.x() for _ in range(4)]
            k.init += [(r, rand_range(1 << 62, 1 << 63)) for r in xin]
            q = [A.x() for _ in range(4)]
            k.init += [(r, 0) for r in q]
            acc = [A.x() for _ in range(8)]
            k.init += [(r, i) for i, r in enumerate(acc)]
            j = 0
            for b in range(B):
                if impl == "hwdep":
                    k.body += [Inst("divu", x, (x, ry)), Inst("add", x, (x, rM))]
                elif impl == "hwind":
                    t = q[b % 4]
                    k.body += [Inst("divu", t, (xin[b % 4], ry)), Inst("xor", sink, (sink, t))]
                elif impl == "muldep":
                    k.body += [Inst("mulhu", x, (x, rmg)), Inst("srli", x, (x,), imm=2), Inst("add", x, (x, rM))]
                elif impl == "mulind":
                    t = q[b % 4]
                    k.body += [Inst("mulhu", t, (xin[b % 4], rmg)), Inst("srli", t, (t,), imm=2),
                               Inst("xor", sink, (sink, t))]
                for _ in range(K):
                    k.body.append(Inst("addi", acc[j % 8], (acc[j % 8],), imm=1))
                    j += 1
            k.outs = [(r, None) for r in [x, sink] + acc]
            ks.append(k)
    return ks


def share_kernels(group):
    ks = []
    for a, b in (("L", "L"), ("S", "S"), ("L", "S")):
        ops = 32
        k = Kernel(f"share_divu_{a}{b}", group, ops,
                   {"cat": "share", "op": "divu", "chainA": a, "chainB": b, "chains": 2})
        A = Alloc()
        regs = []
        for cls in (a, b):
            gx, y, M = opclass("divu", cls)
            rx, ry, rM = A.x(), A.x(), A.x()
            k.init += [(rx, gx()), (ry, y), (rM, M)]
            regs.append((rx, ry, rM))
        for _ in range(ops // 2):
            for rx, ry, rM in regs:
                k.body += [Inst("divu", rx, (rx, ry)), Inst("add", rx, (rx, rM))]
        k.outs = [(r[0], None) for r in regs]
        ks.append(k)
    return ks


# ------------------------------------------ loop-invariant runtime divisor
NARR = 256


def narr_block(data):
    vals = [RNG.getrandbits(32) | (1 << 31) if i % 3 else RNG.getrandbits(32) for i in range(NARR)]
    data.add("narr", [(4, v) for v in vals], align=64)
    return vals


def lemire_c(d):
    return u64((MASK // d) + 1)


def loop_kernels(group, data):
    vals = narr_block(data)
    ks = []
    for d in (7, 10007):
        c = lemire_c(d)
        for n in vals:  # Lemire correctness on the actual data (d > 1)
            assert ((c * n) & MASK) * d >> 64 == n % d
            assert (c * n) >> 64 == n // d
        for T in (4, 16, 64, 256):
            impls = ("ctl", "hwdiv", "hwmod", "lemdiv", "lemmod") if d == 7 else ("hwdiv", "hwmod", "lemdiv", "lemmod")
            for impl in impls:
                k = Kernel(f"inv_d{d}_T{T}_{impl}" if impl != "ctl" else f"inv_T{T}_ctl", group, T,
                           {"cat": "invariant", "d": d, "T": T, "impl": impl})
                A = Alloc()
                p, end, rd, sm, t, rc = A.x(), A.x(), A.x(), A.x(), A.x(), A.x()
                k.init += [(p, ("sym", "narr", 0)), (end, ("sym", "narr", 4 * T)), (rd, d), (sm, 0), (t, 0), (rc, 0)]
                L = f".Lk_{k.name}_loop"
                if impl.startswith("lem"):
                    k.body += [Inst("li", t, (), imm=MASK), Inst("divu", rc, (t, rd)), Inst("addi", rc, (rc,), imm=1)]
                k.body.append(Inst("LABEL", label=L))
                if impl in ("ctl",):
                    k.body += [Inst("lwu", t, (p,), imm=0), Inst("addi", p, (p,), imm=4), Inst("add", sm, (sm, t))]
                elif impl in ("hwdiv", "hwmod"):   # exact GCC 15 -O2 loop shape
                    k.body += [Inst("lw", t, (p,), imm=0), Inst("addi", p, (p,), imm=4),
                               Inst("divuw" if impl == "hwdiv" else "remuw", t, (t, rd)),
                               Inst("slli", t, (t,), imm=32), Inst("srli", t, (t,), imm=32),
                               Inst("add", sm, (sm, t))]
                elif impl == "lemdiv":
                    k.body += [Inst("lwu", t, (p,), imm=0), Inst("addi", p, (p,), imm=4),
                               Inst("mulhu", t, (rc, t)), Inst("add", sm, (sm, t))]
                elif impl == "lemmod":
                    k.body += [Inst("lwu", t, (p,), imm=0), Inst("addi", p, (p,), imm=4),
                               Inst("mul", t, (rc, t)), Inst("mulhu", t, (t, rd)), Inst("add", sm, (sm, t))]
                k.body.append(Inst("bne", None, (end, p), label=L))
                k.outs = [(sm, None)]
                exp = sum(vals[:T]) if impl == "ctl" else sum((n // d if "div" in impl else n % d) for n in vals[:T])
                k.meta["ref_sum"] = u64(exp)
                ks.append(k)
    return ks


# ================================================================== emitters
def emit_kernel(k, data):
    L = []
    nm = f"k_{k.name}"
    L += ["\t.text", "\t.balign 64", f"\t.globl {nm}", f"\t.type {nm}, @function", f"{nm}:"]
    L.append("\taddi\tsp, sp, -208")
    L.append("\tsd\tra, 0(sp)")
    for i in range(12):
        L.append(f"\tsd\ts{i}, {8 + 8 * i}(sp)")
    for i in range(12):
        L.append(f"\tfsd\tfs{i}, {104 + 8 * i}(sp)")
    for i, (r, _) in enumerate(k.init):
        L.append(f"\t{'fld' if is_fp(r) else 'ld'}\t{r}, {8 * i}(a0)")
    L += ["\trdinstret\ta6", "\trdcycle\ta7"]
    L += [ins.asm() for ins in k.body]
    L += ["\trdcycle\ta0", "\trdinstret\tra",
          "\tsub\ta0, a0, a7", "\tsd\ta0, 0(a2)", "\tsub\tra, ra, a6", "\tsd\tra, 8(a2)"]
    for j, (r, sub) in enumerate(k.outs):
        if sub:
            L += [f"\tla\ta0, {sub}", f"\tsub\t{r}, {r}, a0"]
        L.append(f"\t{'fsd' if is_fp(r) else 'sd'}\t{r}, {8 * j}(a1)")
    L.append("\tld\tra, 0(sp)")
    for i in range(12):
        L.append(f"\tld\ts{i}, {8 + 8 * i}(sp)")
    for i in range(12):
        L.append(f"\tfld\tfs{i}, {104 + 8 * i}(sp)")
    L += ["\taddi\tsp, sp, 208", "\tret", f"\t.size {nm}, .-{nm}", ""]
    L += ["\t.section .data", "\t.balign 8", f"\t.globl kin_{k.name}", f"kin_{k.name}:"]
    for r, v in k.init:
        if isinstance(v, tuple):
            L.append(f"\t.dword {v[1]}+{v[2]}")
        else:
            L.append(f"\t.dword {u64(v):#x}")
    if not k.init:
        L.append("\t.dword 0")
    L.append("")
    return L


def evaluate(k, data):
    """Golden checksum + predictions from the Python interpreter."""
    regs = {r: data.resolve(v) for r, v in k.init}
    m = Machine(regs, data.memory())
    trace = m.run(k.body)
    outs = []
    for r, sub in k.outs:
        v = m.x[r]
        if sub:
            v = u64(v - data.base[sub])
        outs.append(v)
    if "ref_sum" in k.meta:
        assert outs[0] == k.meta["ref_sum"], (k.name, outs[0], k.meta["ref_sum"])
    k.expect = fnv(outs)
    k.dyn_insts = len(trace)
    pred = {}
    for model in ("boommd", "rtlsrc"):
        cyc = schedule(trace, model)
        pred[model] = {"cycles": cyc, "per_op": round(cyc / k.ops, 3)}
    from rvmodel import classify, reservations
    cl = {}
    for i, v in trace:
        c = classify(i)
        if c not in cl:
            lat, res = reservations("boommd", i, v)
            occ = max(o for _, _, o in res)
            cl[c] = f"{c}:lat{lat}/occ{occ}"
    pred["boommd"]["classes"] = ";".join(cl[c] for c in sorted(cl))
    divs = [muldiv_core_cycles(i.op, *v)[0] for i, v in trace if i.op in DIV_OPS]
    if divs:
        pred["rtlsrc"]["div_core_cycles_mean"] = round(sum(divs) / len(divs), 2)
        pred["rtlsrc"]["div_core_cycles_minmax"] = [min(divs), max(divs)]
        pred["rtlsrc"]["n_div"] = len(divs)
    k.pred = pred


GROUPS = ["int", "div64", "div32", "fpmem", "divconst", "hide", "loopdiv", "smoke"]
# smoke: a handful of kernels copied from the other groups (same data, same
# golden checksums) for a first, short simulator bring-up run.
SMOKE = ["mul_L_c1", "div_L_c1", "div_S_c1", "divu_L_free", "dc_ud64_13_hw_c1", "dc_ud64_13_seq_c1",
         "fdiv_d_c1", "fmadd_d_c1", "ld_c1", "inv_d7_T64_hwdiv", "inv_d7_T64_lemdiv"]


def build(outdir, gccpath):
    os.makedirs(outdir, exist_ok=True)
    log = []
    groups = {g: ([], Data()) for g in GROUPS}

    def add(g, k):
        groups[g][0].append(k)

    for g in GROUPS:
        for k in ctl_kernels(g):
            add(g, k)
    for op in ("add", "mul", "mulw", "mulh", "mulhu"):
        for cls in ("L", "S"):
            for var, n in VARIANTS:
                add("int", unit_kernel("int", op, cls, var, n, 128))
    for op in ("div", "divu", "rem", "remu"):
        for cls in (("L", "S", "N") if op in ("div", "rem") else ("L", "S")):
            for var, n in VARIANTS:
                add("div64", unit_kernel("div64", op, cls, var, n, 32))
    for op in ("divw", "divuw"):
        for cls in (("L", "S", "N") if op == "divw" else ("L", "S")):
            for var, n in VARIANTS:
                add("div32", unit_kernel("div32", op, cls, var, n, 32))
    for op, ops in (("fdiv.d", 32), ("fsqrt.d", 32), ("fmadd.d", 128)):
        for var, n in VARIANTS:
            add("fpmem", fp_kernel("fpmem", op, var, n, ops))
    for var, n in VARIANTS:
        add("fpmem", load_kernel("fpmem", groups["fpmem"][1], var, n, 128))
    dks, funcs = divconst_kernels("divconst", gccpath, log)
    for k in dks:
        add("divconst", k)
    magic13 = [s[1] for _, _, ss, _ in split_const(funcs["ud64_13"]) for s in ss if s[0] == "c"][0]
    log.append(f"hide: ud64_13 magic {magic13:#x}")
    for k in hide_kernels("hide", magic13) + share_kernels("hide"):
        add("hide", k)
    for cls in ("L", "S"):
        k = unit_kernel("hide", "divu", cls, "c1", 1, 32)
        k.name = "ref_" + k.name   # same-run reference for share_* (names are global)
        add("hide", k)
    for k in loop_kernels("loopdiv", groups["loopdiv"][1]):
        add("loopdiv", k)

    import copy
    byname = {k.name: (g, k) for g, (ks, _) in groups.items() for k in ks}
    for nm in SMOKE:
        g0, k0 = byname[nm]
        k = copy.copy(k0)
        k.group = "smoke"
        add("smoke", k)
        for label, blk in groups[g0][1].blocks.items():
            groups["smoke"][1].blocks.setdefault(label, blk)
    allnames = [k.name for g, (ks, _) in groups.items() if g != "smoke"
                for k in ks if not k.name.startswith("ctl_")]
    assert len(allnames) == len(set(allnames)), "kernel names must be globally unique"
    manifest = {"suite": "megaboom-microbench-v1", "groups": {}, "kernels": []}
    for g, (ks, data) in groups.items():
        data.layout()
        names = set()
        S = [f"/* generated by gen.py: group {g}; do not edit */",
             "\t.option norvc   /* uncompressed: 4-byte fetch granules, exact encodings */"]
        for k in ks:
            assert k.name not in names, k.name
            names.add(k.name)
            evaluate(k, data)
            S += emit_kernel(k, data)
        S += ["\t.section .data"] + data.asm()
        open(os.path.join(outdir, f"{g}_kernels.S"), "w").write("\n".join(S) + "\n")
        C = ["/* generated by gen.py; do not edit */",
             "typedef unsigned long long u64; typedef unsigned int u32;",
             "typedef struct { const char *name; void (*fn)(const u64*, u64*, u64*); const u64 *in;"
             " u32 nout; u32 ops; u64 expect; } kern_t;"]
        for k in ks:
            C.append(f"extern void k_{k.name}(const u64*, u64*, u64*); extern const u64 kin_{k.name}[];")
        C.append("const kern_t KERNELS[] = {")
        for k in ks:
            C.append(f'  {{"{k.name}", k_{k.name}, kin_{k.name}, {len(k.outs)}, {k.ops}, {k.expect:#x}ULL}},')
        C.append("};")
        C.append(f"const unsigned NKERNELS = {len(ks)};")
        C.append(f'const char GROUP[] = "{g}";')
        open(os.path.join(outdir, f"{g}_table.c"), "w").write("\n".join(C) + "\n")
        # simulated-cycle budget estimate: (1 warmup + 3 reps) x (rtlsrc + ~60 serialization)
        est = sum(4 * (k.pred["rtlsrc"]["cycles"] + 60) for k in ks) + 2000 * len(ks)
        manifest["groups"][g] = {"n": len(ks), "est_sim_cycles": est}
        for k in ks:
            manifest["kernels"].append({"name": k.name, "group": g, "ops": k.ops, "meta": k.meta,
                                        "static_insts": sum(1 for i in k.body if i.op != "LABEL"),
                                        "dyn_insts": k.dyn_insts, "expect": f"{k.expect:016x}",
                                        "pred": k.pred})
    seen = {}
    for k in manifest["kernels"]:  # copies (smoke, ctl_*) must agree with originals
        assert seen.setdefault(k["name"], k["expect"]) == k["expect"], k["name"]
    json.dump(manifest, open(os.path.join(outdir, "manifest.json"), "w"), indent=1)
    import csv
    with open(os.path.join(outdir, "predictions.csv"), "w", newline="") as f:
        cols = ["kernel", "group", "cat", "op", "cls", "variant", "chains", "fn", "impl", "K", "T", "d", "ops",
                "dyn_insts", "boommd_cycles", "boommd_per_op", "rtlsrc_cycles", "rtlsrc_per_op",
                "rtlsrc_div_core_mean", "rtlsrc_div_core_minmax", "boommd_classes_lat_occ"]
        w = csv.writer(f)
        w.writerow(cols)
        for k in manifest["kernels"]:
            m, p = k["meta"], k["pred"]
            w.writerow([k["name"], k["group"], m.get("cat", ""), m.get("op", ""), m.get("cls", ""),
                        m.get("variant", ""), m.get("chains", ""), m.get("fn", ""), m.get("impl", ""),
                        m.get("K", ""), m.get("T", ""), m.get("d", ""), k["ops"], k["dyn_insts"],
                        p["boommd"]["cycles"], p["boommd"]["per_op"], p["rtlsrc"]["cycles"], p["rtlsrc"]["per_op"],
                        p["rtlsrc"].get("div_core_cycles_mean", ""),
                        "-".join(map(str, p["rtlsrc"].get("div_core_cycles_minmax", []))),
                        p["boommd"].get("classes", "")])
    open(os.path.join(outdir, "gen.log"), "w").write("\n".join(log) + "\n")
    for g, v in manifest["groups"].items():
        print(f"{g:9s} kernels={v['n']:4d} est_sim_cycles~{v['est_sim_cycles']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "build"))
    ap.add_argument("--gcc-ref", default=os.path.join(ROOT, "gccref", "divc.gcc15.s"))
    a = ap.parse_args()
    build(a.out, a.gcc_ref)
