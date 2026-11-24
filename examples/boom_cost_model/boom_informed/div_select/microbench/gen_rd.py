#!/usr/bin/env python3
"""Range-controlled division microbenchmarks for MegaBOOM (range-aware-div stream).

Reuses the microbench/ framework (kernel emitter, Python RV64 interpreter,
harness, crt, link script) read-only from ../../microbench.

Kernel families (cat):
  dep  : latency chain. x_0 = target_0; for each link i:
           x = OP(x)                 (hw: one div/rem insn; seq: GCC 15.1 body)
           acc ^= x                  (off the critical path; checksum)
           ld t, tab[i+1]; x = x + t (add / addw: 1 ALU cycle on the chain)
         tab[i+1] = target_{i+1} - OP(target_i), so the dividend of link i+1 is
         EXACTLY target_{i+1}: dividends follow the chosen range distribution
         while every link still depends on the previous result.
  ind  : throughput. for each i: ld x, tab[i]; x = OP(x); acc += x
         (rotating register sets, loads independent of the ops).
  ctl_link / ctl_ind: the same skeletons without OP (subtracted in analysis).

OP is one of div/mod over u64/s64/u32/s32 by a constant d, either the hardware
instruction (divisor in a register) or the exact sequence GCC 15.1 -O2 emits
(default tune = rocket; extracted from gccref/rdc.rocket.s, constant
materialization hoisted as in a loop, re-verified here on 20k+ inputs).

Every number this produces is a PREDICTION or a checksum, never a measurement.
"""
import argparse
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MB = os.path.normpath(os.path.join(HERE, "..", "..", "microbench"))
sys.path.insert(0, os.path.join(MB, "gen"))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "rtl-model")))
import gen as G  # noqa: E402
from rvmodel import Inst, Machine, u64, s64, sext32, s32, tdiv  # noqa: E402
from boomhw.muldiv_model import closed_form_cycles, FN_DIV, FN_DIVU, FN_REM, FN_REMU, DW_32, DW_64  # noqa: E402

RNG = random.Random(20261124)
DIVS = [3, 7, 10, 13, 100, 1000]
TYPES = ["u64", "s64", "u32", "s32"]
HWOP = {("u64", "div"): "divu", ("s64", "div"): "div", ("u32", "div"): "divuw", ("s32", "div"): "divw",
        ("u64", "mod"): "remu", ("s64", "mod"): "rem", ("u32", "mod"): "remuw", ("s32", "mod"): "remw"}
FN = {("u64", "div"): (FN_DIVU, DW_64), ("s64", "div"): (FN_DIV, DW_64), ("u32", "div"): (FN_DIVU, DW_32),
      ("s32", "div"): (FN_DIV, DW_32), ("u64", "mod"): (FN_REMU, DW_64), ("s64", "mod"): (FN_REM, DW_64),
      ("u32", "mod"): (FN_REMU, DW_32), ("s32", "mod"): (FN_REM, DW_32)}


def width(t):
    return 64 if t.endswith("64") else 32


def signed(t):
    return t[0] == "s"


def reg(t, v):
    """Python int -> RV64 register representation (32-bit values sign-extended)."""
    return u64(v) if width(t) == 64 else sext32(v)


def ref(t, op, x, d):
    """C semantics on the register representation; returns register repr."""
    w = width(t)
    if signed(t):
        a = s64(x) if w == 64 else s32(x)
        r = tdiv(a, d) if op == "div" else a - d * tdiv(a, d)
    else:
        a = u64(x) if w == 64 else (x & 0xFFFFFFFF)
        r = a // d if op == "div" else a % d
    return reg(t, r)


# ------------------------------------------------------------------ ranges
def msb(v):
    return v.bit_length() - 1 if v > 0 else 0


def ranges_for(t, d):
    """name -> (lo, hi) half-open, as mathematical ints (may be negative)."""
    w = width(t)
    R = {}
    R["lt"] = (0, d)                                   # quotient 0
    if (1 << msb(d)) < d:
        R["samemsb"] = (1 << msb(d), d)                # quotient 0 but msb(a)==msb(d)
    R["d2"] = (d, 2 * d)
    R["d16"] = (d, 16 * d)
    R["b256"] = (0, 256)
    R["p20"] = (1 << 20, 1 << 21)
    if signed(t):
        R["pos"] = (0, 1 << (w - 1))                    # known non-negative, full width
        R["full"] = (-(1 << (w - 1)), 1 << (w - 1))
        R["neg16"] = (-16 * d + 1, -d + 1)
    else:
        R["full"] = (0, 1 << w)
    return R


def draw(lo, hi, n):
    return [RNG.randrange(lo, hi) for _ in range(n)]


# ------------------------------------------------------------ GCC sequences
def load_seqs(path):
    funcs = G.parse_gcc(path)
    seqs = {}
    for t in TYPES:
        for op in ("div", "mod"):
            for d in DIVS:
                body = G.split_const(funcs[f"{t}_{op}_{d}"])
                verify(body, t, op, d)
                seqs[(t, op, d)] = body
    return seqs


def verify(body, t, op, d, nrand=20000):
    temps = sorted({x[1] for _, x, _, _ in body if x != "x"} |
                   {s[1] for _, _, ss, _ in body for s in ss if s[0] == "t"})
    tmap = {tt: f"T{tt}" for tt in temps}
    consts = sorted({s[1] for _, _, ss, _ in body for s in ss if s[0] == "c"})
    cmap = {v: f"C{i}" for i, v in enumerate(consts)}
    prog = G.instantiate(body, "X", tmap, cmap)
    w = width(t)
    edges = [0, 1, 2, d - 1, d, d + 1, 2 * d - 1, 2 * d, 255, 256, (1 << 20), (1 << 21) - 1,
             (1 << w) - 1, 1 << (w - 1), (1 << (w - 1)) - 1, (1 << (w - 1)) + 1,
             -1, -d, -d + 1, -d - 1, -16 * d]
    xs = [reg(t, e) for e in edges] + [reg(t, RNG.getrandbits(64)) for _ in range(nrand)]
    for x in xs:
        m = Machine({"X": x, **{r: v for v, r in cmap.items()}})
        m.run(prog)
        assert m.x["X"] == ref(t, op, x, d), (t, op, d, hex(x), hex(m.x["X"]))
    return len(xs)


# ------------------------------------------------------------------ kernels
def pred_unit(t, op, d, xs):
    fn, dw = FN[(t, op)]
    return [closed_form_cycles(fn, dw, x, d) for x in xs]


def seq_parts(body):
    consts = sorted({s[1] for _, _, ss, _ in body for s in ss if s[0] == "c"})
    temps = sorted({x[1] for _, x, _, _ in body if x != "x"} |
                   {s[1] for _, _, ss, _ in body for s in ss if s[0] == "t"})
    return consts, temps


def dep_kernel(group, data, t, op, d, impl, rname, targets, seqs):
    n = len(targets)
    name = f"dep_{impl}_{t}_{op}_{d}_{rname}"
    k = G.Kernel(name, group, n, {"cat": "dep", "type": t, "op": op, "d": d, "impl": impl, "range": rname})
    A = G.Alloc()
    xr = A.x(); acc = A.x(); tb = A.x(); lt = [A.x(), A.x()]
    xs = [reg(t, v) for v in targets]
    res = [ref(t, op, x, d) for x in xs]
    tab = [0] + [u64(xs[i + 1] - res[i]) for i in range(n - 1)]
    label = f"tab_{name}"
    data.add(label, [(8, v) for v in tab], align=64)
    k.init += [(xr, xs[0]), (acc, 0), (tb, ("sym", label, 0)), (lt[0], 0), (lt[1], 0)]
    if impl == "hw":
        rd = A.x(); k.init.append((rd, d))
        opbody = lambda: [Inst(HWOP[(t, op)], xr, (xr, rd))]  # noqa: E731
    else:
        body = seqs[(t, op, d)]
        consts, temps = seq_parts(body)
        cmap = {}
        for v in consts:
            r = A.x(); cmap[v] = r; k.init.append((r, v))
        tmap = {tt: A.x() for tt in temps}
        for r in tmap.values():
            k.init.append((r, 0))
        opbody = lambda: G.instantiate(body, xr, tmap, cmap)  # noqa: E731
        k.meta["seq"] = [b[0] for b in body]
    addop = "add" if width(t) == 64 else "addw"
    a = 0
    for i in range(n):
        k.body += opbody()
        k.body.append(Inst("xor", acc, (acc, xr)))
        if i < n - 1:
            r = lt[i % 2]
            k.body.append(Inst("ld", r, (tb,), imm=8 * (i + 1)))
            k.body.append(Inst(addop, xr, (xr, r)))
    for v in res:
        a ^= v
    k.meta["ref_sum"] = u64(a)
    k.outs = [(acc, None), (xr, None)]
    if impl == "hw":
        k.meta["unit_cycles"] = pred_unit(t, op, d, xs)
    k.meta["dividends_minmax"] = [min(targets), max(targets)]
    return k


def ind_kernel(group, data, t, op, d, impl, rname, targets, seqs, nsets=3):
    n = len(targets)
    name = f"ind_{impl}_{t}_{op}_{d}_{rname}"
    k = G.Kernel(name, group, n, {"cat": "ind", "type": t, "op": op, "d": d, "impl": impl, "range": rname})
    A = G.Alloc()
    acc = A.x(); tb = A.x()
    xs = [reg(t, v) for v in targets]
    label = f"tab_{name}"
    data.add(label, [(8, v) for v in xs], align=64)
    k.init += [(acc, 0), (tb, ("sym", label, 0))]
    sets = []
    if impl == "hw":
        rd = A.x(); k.init.append((rd, d))
        for _ in range(nsets):
            x = A.x(); k.init.append((x, 0)); sets.append((x, None))
    else:
        body = seqs[(t, op, d)]
        consts, temps = seq_parts(body)
        cmap = {}
        for v in consts:
            r = A.x(); cmap[v] = r; k.init.append((r, v))
        for _ in range(nsets):
            x = A.x(); k.init.append((x, 0))
            tm = {tt: A.x() for tt in temps}
            for r in tm.values():
                k.init.append((r, 0))
            sets.append((x, tm))
        k.meta["seq"] = [b[0] for b in body]
    s = 0
    for i in range(n):
        x, tm = sets[i % nsets]
        k.body.append(Inst("ld", x, (tb,), imm=8 * i))
        if impl == "hw":
            k.body.append(Inst(HWOP[(t, op)], x, (x, rd)))
        else:
            k.body += G.instantiate(body, x, tm, cmap)
        k.body.append(Inst("add", acc, (acc, x)))
        s += ref(t, op, xs[i], d)
    k.meta["ref_sum"] = u64(s)
    k.outs = [(acc, None)]
    if impl == "hw":
        k.meta["unit_cycles"] = pred_unit(t, op, d, xs)
    return k


def ctl_link(group, data, n, w32):
    name = f"ctl_link{'w' if w32 else ''}_{n}"
    k = G.Kernel(name, group, n, {"cat": "ctl_link", "n": n})
    xr, acc, tb, l0, l1 = "s0", "s1", "s2", "s3", "s4"
    tab = [RNG.randrange(0, 1 << 20) for _ in range(n)]
    label = f"tab_{name}"
    data.add(label, [(8, v) for v in tab], align=64)
    k.init += [(xr, 5), (acc, 0), (tb, ("sym", label, 0)), (l0, 0), (l1, 0)]
    for i in range(n):
        k.body.append(Inst("xor", acc, (acc, xr)))
        if i < n - 1:
            r = (l0, l1)[i % 2]
            k.body.append(Inst("ld", r, (tb,), imm=8 * (i + 1)))
            k.body.append(Inst("addw" if w32 else "add", xr, (xr, r)))
    k.outs = [(acc, None), (xr, None)]
    return k


def ctl_ind(group, data, n):
    name = f"ctl_ind_{n}"
    k = G.Kernel(name, group, n, {"cat": "ctl_ind", "n": n})
    acc, tb = "s0", "s1"
    xs = ["s2", "s3", "s4"]
    label = f"tab_{name}"
    data.add(label, [(8, RNG.randrange(0, 1 << 20)) for _ in range(n)], align=64)
    k.init += [(acc, 0), (tb, ("sym", label, 0))] + [(x, 0) for x in xs]
    for i in range(n):
        k.body.append(Inst("ld", xs[i % 3], (tb,), imm=8 * i))
        k.body.append(Inst("add", acc, (acc, xs[i % 3])))
    k.outs = [(acc, None)]
    return k


# --------------------------------------------------------------- groups
def plan(seqs, ops_dep, ops_ind):
    """group -> list of callables producing a kernel given the group's Data.
    Sized for the slow Verilator sim (~60-100 target cycles/s on a loaded a3,
    ~1.8k cycles fixed cost per kernel: cold I$/D$ + harness print)."""
    P = {g: [] for g in ("rdsmoke", "rdseq", "rdgrid", "rdrange64", "rdrange32", "rdrangeb")}

    def targets_for(t, d, rn, n):
        lo, hi = ranges_for(t, d)[rn]
        return draw(lo, hi, n)

    def dep(g, t, op, d, impl, rn, tg):
        P[g].append(lambda D: dep_kernel(g, D, t, op, d, impl, rn, tg, seqs))

    def ind(g, t, op, d, impl, rn, tg):
        P[g].append(lambda D: ind_kernel(g, D, t, op, d, impl, rn, tg, seqs))

    for (t, op, d, rn) in [("u64", "div", 13, "full"), ("u64", "div", 13, "d2"), ("u64", "mod", 10, "d16"),
                           ("s32", "div", 10, "lt")]:
        tg = targets_for(t, d, rn, ops_dep)
        for impl in ("hw", "seq"):
            dep("rdsmoke", t, op, d, impl, rn, tg)
    # rdseq: the GCC 15.1 sequences, latency (all 48) and throughput (d in 7,10,1000)
    for t in TYPES:
        for op in ("div", "mod"):
            for d in DIVS:
                dep("rdseq", t, op, d, "seq", "full", targets_for(t, d, "full", ops_dep))
                if d in (7, 10, 1000):
                    ind("rdseq", t, op, d, "seq", "full", targets_for(t, d, "full", ops_ind))
    # rdgrid: hardware latency vs exact dividend msb: msb(a) = msb(d) + k
    def grid(t, op, d, ks, neg=False):
        v = msb(d)
        for kk in ks:
            if kk == "zero":
                tg, nm = [0] * ops_dep, "a0"
            elif kk < 0:
                m = v + kk
                tg, nm = draw(1 << m, 1 << (m + 1), ops_dep), f"km{-kk}"
            else:
                lo = max(1 << (v + kk), d) if kk == 0 else 1 << (v + kk)
                tg, nm = draw(lo, 1 << (v + kk + 1), ops_dep), f"k{kk}"
            if neg:
                tg, nm = [-x for x in tg], "n" + nm
            dep("rdgrid", t, op, d, "hw", nm, tg)
    grid("u64", "div", 10, ["zero", -3, -2, -1] + list(range(0, 17)) + [30, 59, 60])
    grid("s64", "mod", 10, list(range(0, 13)), neg=True)
    grid("u32", "mod", 1000, ["zero", -1] + list(range(0, 13)))
    grid("s32", "div", 13, list(range(0, 9)), neg=True)
    # throughput: one non-pipelined divider
    for t in ("u64", "s32"):
        for d in (3, 10, 1000):
            for rn in ("d2", "d16", "full", "lt"):
                ind("rdgrid", t, "div", d, "hw", rn, targets_for(t, d, rn, ops_ind))
    # rdrange: hardware latency over named ranges (hw vs seq compared in analysis)
    for (g, cases) in (("rdrange64", [("u64", "div"), ("u64", "mod"), ("s64", "mod")]),
                       ("rdrange32", [("u32", "mod"), ("s32", "div"), ("s32", "mod")])):
        for (t, op) in cases:
            for d in (3, 10, 1000):
                for rn in ranges_for(t, d):
                    dep(g, t, op, d, "hw", rn, targets_for(t, d, rn, ops_dep))
    # wave 3: d in 7, 13, 100.  Its draws are made only when the group is requested, so the
    # wave-2 build (groups rdsmoke..rdrange32) regenerates byte-identically without it.
    for (t, op) in ([] if "rdrangeb" not in WANT else [("u64", "div"), ("u64", "mod"), ("s32", "div"), ("s32", "mod")]):
        for d in (7, 13, 100):
            for rn in ("samemsb", "d2", "d16", "b256", "p20", "lt"):
                dep("rdrangeb", t, op, d, "hw", rn, targets_for(t, d, rn, ops_dep))
    return P


WANT = set()


def build(outdir, gccref, ops_dep, ops_ind, groups):
    WANT.update(groups)
    os.makedirs(outdir, exist_ok=True)
    seqs = load_seqs(gccref)
    P = plan(seqs, ops_dep, ops_ind)
    manifest = {"suite": "range-aware-div-v1", "ops_dep": ops_dep, "ops_ind": ops_ind, "groups": {}, "kernels": []}
    for g in groups:
        data = G.Data()
        ks = [k for k in G.ctl_kernels(g)]
        ks += [ctl_link(g, data, ops_dep, False), ctl_link(g, data, ops_dep, True), ctl_ind(g, data, ops_ind)]
        ks += [f(data) for f in P[g]]
        data.layout()
        S = [f"/* generated by gen_rd.py: group {g}; do not edit */", "\t.option norvc"]
        names = set()
        for k in ks:
            assert k.name not in names, k.name
            names.add(k.name)
            G.evaluate(k, data)
            S += G.emit_kernel(k, data)
        S += ["\t.section .data"] + data.asm()
        open(os.path.join(outdir, f"{g}_kernels.S"), "w").write("\n".join(S) + "\n")
        C = ["/* generated by gen_rd.py; do not edit */",
             "typedef unsigned long long u64; typedef unsigned int u32;",
             "typedef struct { const char *name; void (*fn)(const u64*, u64*, u64*); const u64 *in;"
             " u32 nout; u32 ops; u64 expect; } kern_t;"]
        for k in ks:
            C.append(f"extern void k_{k.name}(const u64*, u64*, u64*); extern const u64 kin_{k.name}[];")
        C.append("const kern_t KERNELS[] = {")
        for k in ks:
            C.append(f'  {{"{k.name}", k_{k.name}, kin_{k.name}, {len(k.outs)}, {k.ops}, {k.expect:#x}ULL}},')
        C += ["};", f"const unsigned NKERNELS = {len(ks)};", f'const char GROUP[] = "{g}";']
        open(os.path.join(outdir, f"{g}_table.c"), "w").write("\n".join(C) + "\n")
        est = 0
        for k in ks:
            u = k.meta.get("unit_cycles")
            body = (sum(u) + 4 * len(u)) if u else 12 * k.ops
            est += 3 * (body + 60) + 2500
        manifest["groups"][g] = {"n": len(ks), "est_sim_cycles": est}
        for k in ks:
            manifest["kernels"].append({"name": k.name, "group": g, "ops": k.ops, "meta": k.meta,
                                        "dyn_insts": k.dyn_insts, "expect": f"{k.expect:016x}"})
        print(f"{g:8s} kernels={len(ks):4d} est_sim_cycles~{est}")
    json.dump(manifest, open(os.path.join(outdir, "manifest.json"), "w"), indent=1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "build"))
    ap.add_argument("--gcc-ref", default=os.path.join(HERE, "gccref", "rdc.rocket.s"))
    ap.add_argument("--ops-dep", type=int, default=16)
    ap.add_argument("--ops-ind", type=int, default=24)
    ap.add_argument("--groups", default="rdsmoke,rdseq,rdgrid,rdrange64,rdrange32")
    a = ap.parse_args()
    build(a.out, a.gcc_ref, a.ops_dep, a.ops_ind, a.groups.split(","))
