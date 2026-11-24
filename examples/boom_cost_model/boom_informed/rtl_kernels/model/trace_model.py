#!/usr/bin/env python3
"""Trace-driven dataflow model of the rtl-kernels timed regions.  [model]

Input: a spike '-l --log-commits' log (stdin or file) of an rtl-kernels ELF and
the group's entry table (from build/<g>_tab.c).  Each TSTART..TSTOP region
(rdcycle;rdinstret ... rdinstret;rdcycle) is one kernel call; per (entry,variant)
there are 1 warmup + REPS calls; the LAST call is modelled.

Two machine models, same scheduler skeleton (4-wide in-order dispatch, ROB 128,
in-order commit 4/cycle, per-port issue, perfect branch prediction, all loads L1 hits):
  rtl    : rtl-model/out/latency_throughput.csv (MegaBoomV3 RTL-derived): alu 1,
           jal/jalr/auipc 4 (int0), mul 6 II1 (int2), div/rem = 2 + MulDiv(a,b) + 1
           latency, MulDiv(a,b)+3 interval (int3 divider, operand dependent,
           rocket MulDiv closed form), int load 4, fp load 5, fp 7 (fp0/fp1),
           f2i 8 (fp0), i2f 6 (int0), fdiv 23/19, fsqrt 31/27 (fp0).
  boommd : Anish's boom.md reservations: alu 1, branch alu0 only, load 3,
           imul 3, fp 4, xfer 3, fdiv 20 (occ 20), fsqrt 25 (occ 25),
           idiv SI 34 / DI 66 (divider held for the whole latency).
Neither model has branch mispredicts or cache misses: they are lower bounds on
the dataflow/resource part.  Compare deltas between variants, not absolutes.
"""
import re, sys, json, collections
sys.path.insert(0, "/scratch/trazzaque/SLICE/boom-research/rtl-model")
from boomhw import muldiv_model as mdm

def sx(v, b):
    v &= (1 << b) - 1
    return v - (1 << b) if v >> (b - 1) else v

# ------------------------------------------------------------------ decoder
# returns (cls, dst, srcs, divinfo) ; regs: x0..31 -> 0..31, f0..31 -> 32..63
def dec32(w):
    op = w & 0x7f; rd = (w >> 7) & 31; f3 = (w >> 12) & 7
    rs1 = (w >> 15) & 31; rs2 = (w >> 20) & 31; f7 = w >> 25
    X = lambda r: r
    Fr = lambda r: 32 + r
    if op == 0x37: return ("alu", X(rd), [], None)
    if op == 0x17: return ("auipc", X(rd), [], None)
    if op == 0x6f: return ("jmp", X(rd), [], None)
    if op == 0x67: return ("jmp", X(rd), [X(rs1)], None)
    if op == 0x63: return ("branch", None, [X(rs1), X(rs2)], None)
    if op == 0x03: return ("load", X(rd), [X(rs1)], None)
    if op == 0x23: return ("store", None, [X(rs1), X(rs2)], None)
    if op in (0x13, 0x1b): return ("alu", X(rd), [X(rs1)], None)
    if op in (0x33, 0x3b):
        if f7 == 1:
            w32 = op == 0x3b
            if f3 < 4: return ("mul", X(rd), [X(rs1), X(rs2)], None)
            fn = {4: mdm.FN_DIV, 5: mdm.FN_DIVU, 6: mdm.FN_REM, 7: mdm.FN_REMU}[f3]
            return ("div", X(rd), [X(rs1), X(rs2)], (fn, 0 if w32 else 1, w32))
        return ("alu", X(rd), [X(rs1), X(rs2)], None)
    if op == 0x73: return ("csr", X(rd), [X(rs1)], None)
    if op == 0x0f: return ("alu", None, [], None)
    if op == 0x2f: return ("load", X(rd), [X(rs1), X(rs2)], None)
    if op == 0x07: return ("fload", Fr(rd), [X(rs1)], None)
    if op == 0x27: return ("fstore", None, [X(rs1), Fr(rs2)], None)
    if op in (0x43, 0x47, 0x4b, 0x4f): return ("fp", Fr(rd), [Fr(rs1), Fr(rs2), Fr(w >> 27)], None)
    if op == 0x53:
        f5 = w >> 27
        if f5 == 0x03: return ("fdiv", Fr(rd), [Fr(rs1), Fr(rs2)], None)
        if f5 == 0x0b: return ("fsqrt", Fr(rd), [Fr(rs1)], None)
        if f5 in (0x14,): return ("f2i", X(rd), [Fr(rs1), Fr(rs2)], None)
        if f5 in (0x18, 0x1c): return ("f2i", X(rd), [Fr(rs1)], None)
        if f5 in (0x1a, 0x1e): return ("i2f", Fr(rd), [X(rs1)], None)
        if f5 in (0x08,): return ("fp", Fr(rd), [Fr(rs1)], None)
        return ("fp", Fr(rd), [Fr(rs1), Fr(rs2)], None)
    raise ValueError(hex(w))

def dec16(h):
    q = h & 3; f3 = h >> 13
    r = lambda lo: (h >> lo) & 31
    rp = lambda lo: 8 + ((h >> lo) & 7)
    if q == 0:
        if f3 == 0: return ("alu", rp(2), [2], None)              # addi4spn
        if f3 == 1: return ("fload", 32 + rp(2), [rp(7)], None)   # fld
        if f3 in (2, 3): return ("load", rp(2), [rp(7)], None)    # lw, ld
        if f3 == 5: return ("fstore", None, [rp(7), 32 + rp(2)], None)
        if f3 in (6, 7): return ("store", None, [rp(7), rp(2)], None)
    if q == 1:
        rd = r(7)
        if f3 == 0: return ("alu", rd, [rd], None)                # addi / nop
        if f3 == 1: return ("alu", rd, [rd], None)                # addiw
        if f3 == 2: return ("alu", rd, [], None)                  # li
        if f3 == 3: return ("alu", rd, [rd] if rd == 2 else [], None)  # addi16sp / lui
        if f3 == 4:
            sub = (h >> 10) & 3; d = rp(7)
            if sub in (0, 1, 2): return ("alu", d, [d], None)
            return ("alu", d, [d, rp(2)], None)
        if f3 == 5: return ("jmp", None, [], None)                # c.j
        if f3 in (6, 7): return ("branch", None, [rp(7)], None)   # beqz/bnez
    if q == 2:
        rd = r(7); rs2 = r(2)
        if f3 == 0: return ("alu", rd, [rd], None)                # slli
        if f3 == 1: return ("fload", 32 + rd, [2], None)          # fldsp
        if f3 in (2, 3): return ("load", rd, [2], None)           # lwsp/ldsp
        if f3 == 4:
            b12 = (h >> 12) & 1
            if b12 == 0:
                if rs2 == 0: return ("jmp", None, [rd], None)      # jr
                return ("alu", rd, [rs2], None)                    # mv
            if rd == 0 and rs2 == 0: return ("alu", None, [], None)  # ebreak
            if rs2 == 0: return ("jmp", 1, [rd], None)              # jalr
            return ("alu", rd, [rd, rs2], None)                    # add
        if f3 == 5: return ("fstore", None, [2, 32 + rs2], None)
        if f3 in (6, 7): return ("store", None, [2, rs2], None)
    raise ValueError(hex(h))

DEC = {}
def decode(word, width16):
    k = (word, width16)
    if k not in DEC:
        DEC[k] = dec16(word) if width16 else dec32(word)
    return DEC[k]

# ------------------------------------------------------------------ models
MDL = {
  "rtl": dict(alu=1, jmp=4, auipc=4, mul=6, load=4, fload=5, fp=7, f2i=8, i2f=6,
              fdiv=(23, 19), fsqrt=(31, 27), branch_ports="alu", csr=1),
  "rtl_bp": None,  # filled below: rtl + gshare branch model + 13-cycle redirect
  "boommd": dict(alu=1, jmp=1, auipc=1, mul=3, load=3, fload=3, fp=4, f2i=3, i2f=3,
                 fdiv=(20, 20), fsqrt=(25, 25), branch_ports="alu0", csr=1),
}

MDL["rtl_bp"] = dict(MDL["rtl"], bp_penalty=13)

class GShare:
    """Stand-in for MegaBOOM's TAGE-L: 64K 2-bit counters, 16-bit global
    history; indirect jumps (not returns) predicted by last target; returns
    perfect (RAS).  Shared across all regions so warmup calls train it."""
    def __init__(self):
        self.t = bytearray([2]) * 65536; self.h = 0; self.btb = {}
    def branch(self, pc, taken):
        i = ((pc >> 1) ^ self.h) & 0xffff
        pred = self.t[i] >= 2
        if taken: self.t[i] = min(3, self.t[i] + 1)
        else: self.t[i] = max(0, self.t[i] - 1)
        self.h = ((self.h << 1) | int(taken)) & 0xffff
        return pred != taken
    def indirect(self, pc, target):
        m = self.btb.get(pc) != target
        self.btb[pc] = target
        return m

def div_cost(model, info, a, b):
    fn, dw, w32 = info
    if model in ("rtl", "rtl_bp"):
        L = mdm.closed_form_cycles(fn, dw, a & (2**64 - 1), b & (2**64 - 1))
        return 2 + L + 1, L + 3, L
    lat = 34 if w32 else 66
    return lat, lat, None

class Sched:
    """Back-filling list scheduler: each uop issues at the earliest cycle >= its
    dispatch+1 and operand-ready time at which a port (and, for div/fdiv/fsqrt,
    the unpipelined unit for its whole occupancy) is free.  This approximates
    BOOM's oldest-ready-first out-of-order issue within the ROB window."""
    def __init__(self, model):
        self.m = model; P = MDL[model]; self.P = P
        self.ready = [0] * 64
        self.port_busy = collections.defaultdict(set)   # cycle -> ports used
        self.unit_busy = {"div": [], "fdiv": []}          # list of [start, end)
        self.commit = collections.deque(maxlen=128)
        self.n = 0; self.last_disp = 0; self.disp_cnt = 0; self.last_commit = 0; self.commit_cnt = 0
        self.end = 0; self.divs = []; self.redirect = 0; self.mispred = 0
    def unit_ok(self, unit, t, occ):
        for a, b in self.unit_busy[unit]:
            if t < b and a < t + occ:
                return False, b
        return True, None
    def pick(self, ports, t, unit=None, occ=0):
        while True:
            used = self.port_busy.get(t)
            free = [p for p in ports if not used or p not in used]
            if free:
                if unit is None:
                    break
                ok, nxt = self.unit_ok(unit, t, occ)
                if ok:
                    break
                t = nxt
                continue
            t += 1
        self.port_busy[t].add(free[0])
        if unit is not None:
            self.unit_busy[unit].append((t, t + occ))
        return t
    def prune(self, d):
        if self.n % 4096 == 0:
            for c in [c for c in self.port_busy if c < d]:
                del self.port_busy[c]
            for u in self.unit_busy:
                self.unit_busy[u] = [iv for iv in self.unit_busy[u] if iv[1] > d]
    def run(self, cls, dst, srcs, divinfo, vals, mis=False):
        P = self.P
        d = max(self.last_disp, self.redirect)
        if self.disp_cnt >= 4: d += 1; self.disp_cnt = 0
        if len(self.commit) == 128: d = max(d, self.commit[0] + 1)
        if d != self.last_disp: self.disp_cnt = 0
        self.last_disp = d; self.disp_cnt += 1
        self.prune(d)
        t = d + 1
        for s_ in srcs:
            if s_ != 0: t = max(t, self.ready[s_])
        INT = ["int0", "int1", "int2", "int3"]
        if cls in ("alu", "csr"):
            t = self.pick(INT, t); lat = 1
        elif cls == "branch":
            t = self.pick(["int0"] if P["branch_ports"] == "alu0" else INT, t); lat = 1
        elif cls in ("jmp", "auipc"):
            t = self.pick(["int0"], t); lat = P[cls]
        elif cls == "mul":
            t = self.pick(["int2"], t); lat = P["mul"]
        elif cls == "div":
            lat, occ, L = div_cost(self.m, divinfo, vals[0], vals[1])
            t = self.pick(["int3"], t, "div", occ)
            self.divs.append((lat, L))
        elif cls in ("load", "store"):
            t = self.pick(["mem0", "mem1"], t); lat = P["load"]
        elif cls == "fload":
            t = self.pick(["mem0", "mem1"], t); lat = P["fload"]
        elif cls == "fstore":
            t = self.pick(["mem0", "mem1"], t); lat = 1
        elif cls == "fp":
            t = self.pick(["fp0", "fp1"], t); lat = P["fp"]
        elif cls == "f2i":
            t = self.pick(["fp0"], t); lat = P["f2i"]
        elif cls == "i2f":
            t = self.pick(["int0"], t); lat = P["i2f"]
        elif cls in ("fdiv", "fsqrt"):
            lat, occ = P[cls]
            t = self.pick(["fp0"], t, "fdiv", occ)
        else:
            raise ValueError(cls)
        if dst is not None and dst != 0:
            self.ready[dst] = t + lat
        if mis and P.get("bp_penalty"):
            self.redirect = t + 1 + P["bp_penalty"]; self.mispred += 1
        done = t + lat
        c = max(done, self.last_commit)
        if c == self.last_commit:
            self.commit_cnt += 1
            if self.commit_cnt > 4: c += 1; self.commit_cnt = 1
        else:
            self.commit_cnt = 1
        self.last_commit = c
        self.commit.append(c)
        self.end = max(self.end, c)
        self.n += 1

LINE_I = re.compile(r"^core\s+0: 0x([0-9a-f]+) \(0x([0-9a-f]+)\) (\S+)")
LINE_C = re.compile(r"^core\s+0: 3 0x([0-9a-f]+) \(0x([0-9a-f]+)\)(.*)$")
WR = re.compile(r"\b([xf])(\d+)\s+0x([0-9a-f]+)")

def main():
    log = sys.argv[1]; tab = sys.argv[2]; out = sys.argv[3]
    reps = int(sys.argv[4]) if len(sys.argv) > 4 else 2
    ents = re.findall(r'\{"([^"]+)", "([^"]+)", ', open(tab).read())
    calls = [(k, v, c) for (k, v) in ents for c in range(1 + reps)]
    regs = [0] * 64
    region = -1; rec = False; prev_mn = None
    scheds = None; results = []
    pend = None
    bp = GShare()
    def flush(p, next_pc):
        cls, dst, srcs, di, vals, pc, ln, word, isret = p
        mis = False
        if next_pc is not None:
            if cls == "branch":
                mis = bp.branch(pc, next_pc != pc + ln)
            elif cls == "jmp" and srcs and not isret:
                mis = bp.indirect(pc, next_pc)
        for sc in scheds.values():
            sc.run(cls, dst, srcs, di, vals, mis)
    fh = sys.stdin if log == "-" else open(log, errors="replace")
    for line in fh:
        if line.startswith("core   0: 3 "):
            m = LINE_C.match(line)
            if not m: continue
            for xf, n, v in WR.findall(m.group(3)):
                regs[int(n) + (32 if xf == "f" else 0)] = int(v, 16)
            continue
        m = LINE_I.match(line)
        if not m: continue
        wd = int(m.group(2), 16)
        mn = None
        if (wd & 0x707f) == 0x2073 and ((wd >> 15) & 31) == 0:
            mn = {0xc00: "rdcycle", 0xc02: "rdinstret"}.get(wd >> 20)
        if mn == "rdinstret" or mn == "rdcycle":
            if mn == "rdinstret" and prev_mn == "rdcycle" and not rec:
                rec = True; region += 1
                scheds = {k: Sched(k) for k in MDL}; cnt = collections.Counter(); divvals = []
            elif mn == "rdinstret" and rec:
                if pend is not None:
                    flush(pend, None); pend = None
                rec = False
                k, v, c = calls[region]
                if c == reps:
                    r = dict(k=k, v=v, insts=scheds["rtl"].n, classes=dict(cnt))
                    for nm, s in scheds.items():
                        r["cyc_" + nm] = s.end
                    r["mispred_gshare"] = scheds["rtl_bp"].mispred
                    dv = scheds["rtl"].divs
                    r["ndiv"] = len(dv)
                    r["div_lat_rtl_avg"] = round(sum(x[0] for x in dv) / len(dv), 2) if dv else None
                    results.append(r)
            prev_mn = mn
            continue
        if not rec: continue
        word = int(m.group(2), 16); w16 = (word & 3) != 3
        pc = int(m.group(1), 16)
        if pend is not None:
            flush(pend, pc)
        cls, dst, srcs, di = decode(word, w16)
        cnt[cls] += 1
        vals = (regs[srcs[0]], regs[srcs[1]]) if cls == "div" else None
        isret = cls == "jmp" and dst in (None, 0) and srcs == [1]
        pend = (cls, dst, srcs, di, vals, pc, 2 if w16 else 4, word, isret)
    assert region + 1 == len(calls), (region + 1, len(calls))
    json.dump(results, open(out, "w"), indent=1)
    for r in results:
        print(f"{r['k']:22s} {r['v']:7s} insts={r['insts']:7d} rtl={r['cyc_rtl']:8d} rtl_bp={r['cyc_rtl_bp']:8d} mis={r['mispred_gshare']:5d} boommd={r['cyc_boommd']:8d} ndiv={r['ndiv']} divlat={r['div_lat_rtl_avg']}")

if __name__ == "__main__":
    main()
