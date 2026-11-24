"""Tiny RV64 interpreter + two analytic timing models for the microbench suite.

Interpreter: independent (Python) semantics for exactly the instruction subset
the generated kernels use.  It is the golden reference for each kernel's
checksum; spike is a second, independent check.

Timing models (both are PREDICTIONS, never measurements):
  * "boommd": the reservations of Anish's hand-written GCC boom.md
    (chia/chipyard/boom_model.py on origin/main): alu 1 (4 pooled ALUs),
    imul 3 (alu+boom_mul, 1-cycle occupancy), idiv SI 34 / DI 66 (boom_div
    occupied for the full latency), load 3 (2 mem), fp/fmadd 4 (2 fp),
    fdiv 20 / fsqrt 25 (boom_fdiv occupied for the full latency), issue 4.
  * "rtlsrc": a first-principles estimate from reading riscv-boom 5223e44c +
    rocket-chip MulDiv(divUnroll=1, divEarlyOut=true): data-dependent integer
    divide iteration count; ASSUMED BOOM wrapper overheads.  Unvalidated.
Both are evaluated on the dynamic trace with an idealized dataflow scheduler
(infinite window, in-trace-order greedy resource allocation, 4 issue/cycle).
"""

import struct
from fractions import Fraction

MASK = (1 << 64) - 1


def u64(x):
    return x & MASK


def s64(x):
    x &= MASK
    return x - (1 << 64) if x >> 63 else x


def sext32(x):
    x &= 0xFFFFFFFF
    return u64(x - (1 << 32) if x >> 31 else x)


def s32(x):
    x &= 0xFFFFFFFF
    return x - (1 << 32) if x >> 31 else x


def tdiv(a, b):  # C/RISC-V truncating division on Python ints, b != 0
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b >= 0) else -q


def f2b(f):
    return struct.unpack("<Q", struct.pack("<d", f))[0]


def b2f(b):
    return struct.unpack("<d", struct.pack("<Q", b & MASK))[0]


def fma_d(a, b, c):
    """Correctly rounded a*b+c for finite doubles via exact rationals."""
    r = Fraction(a) * Fraction(b) + Fraction(c)
    return float(r)


# ---------------------------------------------------------------- integer ops
def _div(a, b):
    a, b = s64(a), s64(b)
    if b == 0:
        return MASK
    if a == -(1 << 63) and b == -1:
        return u64(a)
    return u64(tdiv(a, b))


def _divu(a, b):
    a, b = u64(a), u64(b)
    return MASK if b == 0 else a // b


def _rem(a, b):
    a, b = s64(a), s64(b)
    if b == 0:
        return u64(a)
    if a == -(1 << 63) and b == -1:
        return 0
    return u64(a - b * tdiv(a, b))


def _remu(a, b):
    a, b = u64(a), u64(b)
    return a if b == 0 else a % b


def _divw(a, b):
    a, b = s32(a), s32(b)
    if b == 0:
        return MASK
    if a == -(1 << 31) and b == -1:
        return sext32(a)
    return sext32(tdiv(a, b))


def _divuw(a, b):
    a, b = a & 0xFFFFFFFF, b & 0xFFFFFFFF
    return MASK if b == 0 else sext32(a // b)


def _remw(a, b):
    a, b = s32(a), s32(b)
    if b == 0:
        return sext32(a)
    if a == -(1 << 31) and b == -1:
        return 0
    return sext32(a - b * tdiv(a, b))


def _remuw(a, b):
    a, b = a & 0xFFFFFFFF, b & 0xFFFFFFFF
    return sext32(a if b == 0 else a % b)


R3 = {
    "add": lambda a, b: u64(a + b),
    "sub": lambda a, b: u64(a - b),
    "addw": lambda a, b: sext32(a + b),
    "subw": lambda a, b: sext32(a - b),
    "or": lambda a, b: u64(a | b),
    "xor": lambda a, b: u64(a ^ b),
    "and": lambda a, b: u64(a & b),
    "mul": lambda a, b: u64(a * b),
    "mulw": lambda a, b: sext32(a * b),
    "mulh": lambda a, b: u64((s64(a) * s64(b)) >> 64),
    "mulhu": lambda a, b: u64((u64(a) * u64(b)) >> 64),
    "div": _div, "divu": _divu, "rem": _rem, "remu": _remu,
    "divw": _divw, "divuw": _divuw, "remw": _remw, "remuw": _remuw,
}
RI = {
    "addi": lambda a, i: u64(a + i),
    "addiw": lambda a, i: sext32(a + i),
    "ori": lambda a, i: u64(a | i),
    "xori": lambda a, i: u64(a ^ i),
    "andi": lambda a, i: u64(a & i),
    "slli": lambda a, i: u64(a << i),
    "srli": lambda a, i: u64(a) >> i,
    "srai": lambda a, i: u64(s64(a) >> i),
    "slliw": lambda a, i: sext32(a << i),
    "srliw": lambda a, i: sext32((a & 0xFFFFFFFF) >> i),
    "sraiw": lambda a, i: sext32(s32(a) >> i),
}
LOADS = {"ld": (8, False), "lw": (4, True), "lwu": (4, False)}
BRANCH = {"bnez", "bne", "beqz"}
FP3 = {"fdiv.d", "fadd.d", "fmul.d"}
FP_OPS = FP3 | {"fsqrt.d", "fmadd.d"}

DIV_OPS = {"div", "divu", "rem", "remu", "divw", "divuw", "remw", "remuw"}
MUL_OPS = {"mul", "mulw", "mulh", "mulhu"}


class Inst:
    """op rd, rs1, rs2[, rs3] / op rd, rs1, imm / ld rd, imm(rs1) / branch / label."""

    __slots__ = ("op", "rd", "rs", "imm", "label")

    def __init__(self, op, rd=None, rs=(), imm=None, label=None):
        self.op, self.rd, self.rs, self.imm, self.label = op, rd, tuple(rs), imm, label

    def asm(self):
        o = self.op
        if o == "LABEL":
            return f"{self.label}:"
        if o in LOADS:
            return f"\t{o}\t{self.rd}, {self.imm}({self.rs[0]})"
        if o == "bnez":
            return f"\tbnez\t{self.rs[0]}, {self.label}"
        if o == "bne":
            return f"\tbne\t{self.rs[0]}, {self.rs[1]}, {self.label}"
        if o == "li":
            return f"\tli\t{self.rd}, {s64(self.imm)}"
        if o in RI:
            return f"\t{o}\t{self.rd}, {self.rs[0]}, {self.imm}"
        return f"\t{o}\t{self.rd}, " + ", ".join(self.rs)

    def __repr__(self):
        return self.asm().strip()


class Machine:
    def __init__(self, regs=None, mem=None):
        self.x = dict(regs or {})
        self.mem = dict(mem or {})  # byte address -> byte

    def rd(self, r):
        return 0 if r == "zero" else self.x[r]

    def wr(self, r, v):
        if r != "zero":
            self.x[r] = u64(v)

    def load(self, addr, size, signed):
        v = 0
        for i in range(size):
            v |= self.mem[addr + i] << (8 * i)
        if signed and v >> (8 * size - 1):
            v -= 1 << (8 * size)
        return u64(v)

    def run(self, prog, max_steps=10_000_000):
        """Execute prog; return dynamic trace [(Inst, srcvals)]."""
        labels = {i.label: k for k, i in enumerate(prog) if i.op == "LABEL"}
        trace, pc, steps = [], 0, 0
        while pc < len(prog):
            steps += 1
            assert steps < max_steps, "runaway"
            ins = prog[pc]
            o = ins.op
            pc += 1
            if o == "LABEL":
                continue
            vals = tuple(self.rd(r) for r in ins.rs)
            trace.append((ins, vals))
            if o in R3:
                self.wr(ins.rd, R3[o](*vals))
            elif o in RI:
                self.wr(ins.rd, RI[o](vals[0], ins.imm))
            elif o == "li":
                self.wr(ins.rd, ins.imm)
            elif o in LOADS:
                size, sg = LOADS[o]
                self.wr(ins.rd, self.load(u64(vals[0] + ins.imm), size, sg))
            elif o == "bnez":
                if vals[0] != 0:
                    pc = labels[ins.label]
            elif o == "bne":
                if vals[0] != vals[1]:
                    pc = labels[ins.label]
            elif o in FP3:
                a, b = b2f(vals[0]), b2f(vals[1])
                r = {"fdiv.d": a / b if b else float("inf"), "fadd.d": a + b, "fmul.d": a * b}[o]
                self.wr(ins.rd, f2b(r))
            elif o == "fsqrt.d":
                import math
                self.wr(ins.rd, f2b(math.sqrt(b2f(vals[0]))))
            elif o == "fmadd.d":
                self.wr(ins.rd, f2b(fma_d(*(b2f(v) for v in vals))))
            else:
                raise ValueError(f"unsupported op {o}")
        return trace


# ---------------------------------------------------------- MulDiv RTL model
def _log2(v):
    return v.bit_length() - 1 if v else 0


def muldiv_core_cycles(op, a, b):
    """Cycles from req.fire to resp.valid in rocket MulDiv(divUnroll=1,
    divEarlyOut=true, granularity 1, w=64), from reading Multiplier.scala at
    rocket-chip 55bcad0f.  Returns (cycles, detail dict)."""
    half = op.endswith("w")
    signed = op in ("div", "rem", "divw", "remw")
    is_rem = op.startswith("rem")

    def ext(x):
        if half:
            x &= 0xFFFFFFFF
            sign = signed and (x >> 31) & 1
            return (x | (0xFFFFFFFF << 32)) if sign else x, sign
        x &= MASK
        return x, signed and (x >> 63)

    lhs, ls = ext(a)
    rhs, rs = ext(b)
    neg_in = 1 if (ls or rs) else 0
    mag_l = u64(-lhs) if ls else lhs
    mag_r = u64(-rhs) if rs else rhs
    divby0 = mag_r == 0
    if divby0:
        s_div = 65
    else:
        diff = (_log2(mag_l) - _log2(mag_r)) & 63
        eoutpos = (~diff) & 63
        s_div = 66 - eoutpos if eoutpos >= 1 else 65
    neg_out = (ls if is_rem else (ls != rs)) and not (divby0 and not is_rem)
    cyc = neg_in + s_div + (1 if neg_out else 0) + 1
    return cyc, {"neg_in": neg_in, "s_div": s_div, "neg_out": int(bool(neg_out))}


# ------------------------------------------------------------- timing models
ALU = ("alu", 4)
MEM = ("mem", 2)
FPP = ("fp", 2)

# Assumed BOOM wrapper overhead around the iterative divider (issue/regread/
# writeback/wakeup).  NOT derived precisely; the measurement calibrates it.
RTL_DIV_LAT_OVERHEAD = 3
RTL_DIV_OCC_OVERHEAD = 3


def classify(ins):
    o = ins.op
    if o in DIV_OPS:
        return "idiv_si" if o.endswith("w") else "idiv_di"
    if o in MUL_OPS:
        return "imul"
    if o in LOADS:
        return "load"
    if o in BRANCH:
        return "branch"
    if o in ("fdiv.d",):
        return "fdiv"
    if o == "fsqrt.d":
        return "fsqrt"
    if o in FP_OPS:
        return "fp"
    return "alu"


def reservations(model, ins, vals):
    """-> (latency, [(pool_name, pool_size, occupancy_cycles), ...])"""
    c = classify(ins)
    if model == "boommd":
        if c == "alu":
            return 1, [("alu", 4, 1)]
        if c == "branch":
            return 1, [("alu", 1, 1)]  # alu0 only (k=0 of the alu pool)
        if c == "load":
            return 3, [("mem", 2, 1)]
        if c == "imul":
            return 3, [("alu", 4, 1), ("mul", 1, 1)]
        if c == "fp":
            return 4, [("fp", 2, 1)]
        if c == "fdiv":
            return 20, [("fp", 2, 1), ("fdiv", 1, 20)]
        if c == "fsqrt":
            return 25, [("fp", 2, 1), ("fdiv", 1, 25)]
        if c == "idiv_si":
            return 34, [("alu", 4, 1), ("div", 1, 34)]
        if c == "idiv_di":
            return 66, [("alu", 4, 1), ("div", 1, 66)]
    elif model == "rtlsrc":
        if c in ("alu", "branch"):
            return 1, [("alu", 4, 1)]
        if c == "load":
            return 4, [("mem", 2, 1)]          # assumed L1-hit load-to-use
        if c == "imul":
            return 3, [("alu", 4, 1), ("mul", 1, 1)]  # imulLatency=3, 1 unit
        if c == "fp":
            return 4, [("fp", 2, 1)]           # dfmaLatency=4
        if c == "fdiv":
            return 20, [("fp", 2, 1), ("fdiv", 1, 20)]  # not derived: placeholder
        if c == "fsqrt":
            return 25, [("fp", 2, 1), ("fdiv", 1, 25)]  # not derived: placeholder
        if c in ("idiv_si", "idiv_di"):
            core, _ = muldiv_core_cycles(ins.op, vals[0], vals[1])
            return core + RTL_DIV_LAT_OVERHEAD, [("alu", 4, 1), ("div", 1, core + RTL_DIV_OCC_OVERHEAD)]
    raise ValueError((model, c))


def schedule(trace, model, issue_width=4):
    """Idealized dataflow schedule; returns total cycles (makespan)."""
    ready = {}          # reg -> cycle value available
    busy = {}           # (pool, idx) -> set of busy cycles
    issued = {}         # cycle -> count
    makespan = 0
    for ins, vals in trace:
        lat, res = reservations(model, ins, vals)
        t = max([ready.get(r, 0) for r in ins.rs if r != "zero"] + [0])
        while True:
            if issued.get(t, 0) < issue_width:
                picks, ok = [], True
                for pool, n, occ in res:
                    for k in range(n):
                        bs = busy.setdefault((pool, k), set())
                        if all((t + j) not in bs for j in range(occ)):
                            picks.append(((pool, k), occ))
                            break
                    else:
                        ok = False
                        break
                if ok:
                    break
            t += 1
        for key, occ in picks:
            busy[key].update(range(t, t + occ))
        issued[t] = issued.get(t, 0) + 1
        if ins.rd and ins.op not in BRANCH:
            ready[ins.rd] = t + lat
        makespan = max(makespan, t + lat)
    return makespan
