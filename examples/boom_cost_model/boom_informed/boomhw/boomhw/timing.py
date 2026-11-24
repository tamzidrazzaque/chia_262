"""Predicted per-class latency / reciprocal throughput for MegaBOOM V3.

Definitions (all in core clock cycles):
  latency     = issue cycle of producer -> earliest issue cycle of a dependent
                consumer (the quantity a GCC define_insn_reservation latency
                models).  Measured in a dependent chain this is cycles/op.
  recip_thpt  = steady-state cycles per op for independent ops of the class
                (port/unit occupancy), ignoring front-end and ROB limits.

Basis labels:
  'unit-RTL'  : the functional unit's own cycles were measured by Verilator on
                the unit cut from the FireSim MegaBOOM elaborated FIRRTL
                (rtl_unit_sim/), and the core pipeline offsets are 'derived'.
  'derived'   : computed from generator parameters + code anchors (no sim).
  'estimate'  : derived from a stage count with known uncertainty.
None of these numbers is a full-core RTL, FireSim, spike or QEMU measurement.
"""
from . import muldiv_model as mdm

ISSUE_TO_EX = 2          # issue -> RR -> EX  (anchors rrd_regnext, exe_reg)
SLOW_WAKEUP = 1          # result on writeback port in cycle t -> dependent issues t+1
HF_DIV_CORE = 18         # hardfloat DivSqrtRecF64 fire->outValid, div (unit-RTL)
HF_SQRT_CORE = 26        # ... sqrt (unit-RTL)


def hf_core_cycles(phases):
    """Fire->outValid of DivSqrtRecF64_mulAddZ31 from its phase counters:
    (A+1) + B + C + E - 1 for the normal case."""
    a_div, a_sqrt = phases["A_div"]["groups"][0], phases["A_sqrt"]["groups"][0]
    b_sqrt, b_div = phases["B"]["groups"]
    c_sqrt, c_div = phases["C"]["groups"]
    e = phases["E"]["groups"][0]
    return (a_div + 1) + b_div + c_div + e - 1, (a_sqrt + 1) + b_sqrt + c_sqrt + e - 1


def div_core_latency(fn, dw, a, b):
    """Issue->dependent-issue latency of one integer div/rem (derived; MulDiv
    cycles are unit-RTL exact)."""
    L = mdm.closed_form_cycles(fn, dw, a, b)
    return ISSUE_TO_EX + L + SLOW_WAKEUP


def div_core_interval(fn, dw, a, b):
    """Issue->next-div-issue interval for back-to-back independent divides.
    MulDiv ready the cycle after resp.fire (unit-RTL: ready_gap=1); div_busy is
    combinational so the next div issues that cycle and fires ISSUE_TO_EX later."""
    L = mdm.closed_form_cycles(fn, dw, a, b)
    return L + 1 + ISSUE_TO_EX


M64 = (1 << 64) - 1
DIV_CASES = [
    # (label, fn, dw, a, b)
    ("divu 64b, equal MSB (best case, e.g. 1000/600)", mdm.FN_DIVU, 1, 1000, 600),
    ("divu 64b, small: 1000/10", mdm.FN_DIVU, 1, 1000, 10),
    ("divu 64b, 2^32-scale / 10", mdm.FN_DIVU, 1, 0x9_0000_0000, 10),
    ("divu 64b, full 64-bit dividend / 10", mdm.FN_DIVU, 1, 0xF123_4567_89AB_CDEF, 10),
    ("divu 64b, x / 1 with x >= 2^63 (no early-out)", mdm.FN_DIVU, 1, 1 << 63, 1),
    ("divu 64b, quotient 0: 5/13 (no early-out)", mdm.FN_DIVU, 1, 5, 13),
    ("divu 64b, zero dividend: 0/3 (no early-out)", mdm.FN_DIVU, 1, 0, 3),
    ("divu 64b, divide by zero", mdm.FN_DIVU, 1, 12345, 0),
    ("div 64b signed, full / -10 (neg in + neg out)", mdm.FN_DIV, 1, 0x7123_4567_89AB_CDEF, (-10) & M64),
    ("div 64b signed, worst: -5 / 13", mdm.FN_DIV, 1, (-5) & M64, 13),
    ("rem 64b, full 64-bit / 10", mdm.FN_REMU, 1, 0xF123_4567_89AB_CDEF, 10),
    ("divw 32b, full 31-bit dividend / 10", mdm.FN_DIV, 0, 0x7123_4567, 10),
    ("divuw 32b, full 32-bit dividend / 10", mdm.FN_DIVU, 0, 0xF123_4567, 10),
    ("divw 32b, 1000/10", mdm.FN_DIV, 0, 1000, 10),
    ("divw 32b, quotient 0: 5/13", mdm.FN_DIV, 0, 5, 13),
]


def div_table():
    rows = []
    for label, fn, dw, a, b in DIV_CASES:
        L = mdm.closed_form_cycles(fn, dw, a, b)
        rows.append({"case": label, "fn": fn, "dw": dw, "a": hex(a), "b": hex(b),
                     "muldiv_fire_to_resp": L,
                     "latency": div_core_latency(fn, dw, a, b),
                     "recip_thpt": div_core_interval(fn, dw, a, b),
                     "basis": "unit-RTL (MulDiv cycles) + derived (core +3)"})
    return rows


def class_table(model):
    c = model["core"]
    fp = model["fpu_params"]
    imul = c["imulLatency"]["value"]
    i2f = c["intToFpLatency"]["value"]
    dfma = fp["dfmaLatency"]["value"]
    ports = model["exec_ports"]
    alu_ports = [p["port"] for p in ports["int"] if "ALU" in p["fus"]]
    port_of = lambda fu: [p["port"] for p in ports["int"] if fu in p["fus"]]
    memp = [p["port"] for p in ports["mem"]]
    fpp = [p["port"] for p in ports["fp"]]
    fdivp = [p["port"] for p in ports["fp"] if any("FDIV" in f for f in p["fus"])]
    f2ip = [p["port"] for p in ports["fp"] if any("F2I" in f for f in p["fus"])]
    hf_div, hf_sqrt = hf_core_cycles(model["hardfloat_divsqrt_phases"])
    A = model["anchors"]
    s = lambda *keys: [A[k]["src"] for k in keys]
    div_full = div_core_latency(mdm.FN_DIVU, 1, 0xF123_4567_89AB_CDEF, 10)
    divw_full = div_core_latency(mdm.FN_DIV, 0, 0x7123_4567, 10)
    rows = [
        dict(cls="int_alu", insns="add/sub/logic/shift/slt/lui/addi/addw/sext", gcc_types="arith,logical,shift,slt,const,move,nop,multi",
             ports=alu_ports, latency=1, recip_thpt=1 / len(alu_ports), basis="derived",
             src=s("fast_wakeup", "slot_wakeup_reg")),
        dict(cls="cond_branch", insns="beq/bne/blt/bge/bltu/bgeu", gcc_types="branch",
             ports=alu_ports, latency=None, recip_thpt=1 / len(alu_ports), basis="derived",
             note="branches are FU_ALU: resolve on any of the 4 ALUs (not only the JMP port)",
             src=[model["decode"]["BEQ"]["src"]]),
        dict(cls="jal_jalr_call_ret", insns="jal/jalr/call/ret", gcc_types="jump,jalr,call,ret",
             ports=port_of("JMP"), latency=ISSUE_TO_EX + 1 + SLOW_WAKEUP, recip_thpt=1.0, basis="derived",
             note="FU_JMP only on int0; not bypassable -> link value via slow wakeup",
             src=[model["decode"]["JALR"]["src"]] + s("slow_wakeup")),
        dict(cls="auipc", insns="auipc", gcc_types="auipc",
             ports=port_of("JMP"), latency=ISSUE_TO_EX + 1 + SLOW_WAKEUP, recip_thpt=1.0, basis="derived",
             note="AUIPC is FU_JMP, bypassable=N: 4-cycle latency, int0 only",
             src=[model["decode"]["AUIPC"]["src"]] + s("slow_wakeup", "pfu_resp")),
        dict(cls="csr", insns="csrr*/frflags/fsflags", gcc_types="rdfrm,wrfrm,wrvxrm,rdvlenb,rdvl,trap",
             ports=port_of("CSR"), latency=None, recip_thpt=None, basis="derived",
             note="CSR unit on int1; CSR writes are unique/serializing (flush on commit)",
             src=[model["decode"]["CSRRW"]["src"]]),
        dict(cls="imul", insns="mul/mulw/mulh/mulhu/mulhsu", gcc_types="imul",
             ports=port_of("IMUL"), latency=ISSUE_TO_EX + imul + SLOW_WAKEUP, recip_thpt=1.0,
             basis="unit-RTL (PipelinedMultiplier latency=3, II=1) + derived",
             note="mulh* run on the pipelined multiplier, not on MulDiv",
             src=[model["decode"]["MULHU"]["src"]] + s("imul_unit", "pfu_resp", "slow_wakeup")),
        dict(cls="idiv_64", insns="div/divu/rem/remu", gcc_types="idiv (DI)",
             ports=port_of("IDIV"), latency=f"7..71 operand-dependent; {div_full} for full-width/10",
             recip_thpt="= latency (one divide in flight)", basis="unit-RTL (MulDiv) + derived",
             note="iterative; ALU on int3 stays issuable while dividing",
             src=s("div_unit", "div_busy", "div_fu_types", "div_issue_mask", "div_wb_share")),
        dict(cls="idiv_32", insns="divw/divuw/remw/remuw", gcc_types="idiv (SI)",
             ports=port_of("IDIV"), latency=f"7..71 operand-dependent; {divw_full} for full 31-bit/10",
             recip_thpt="= latency", basis="unit-RTL (MulDiv) + derived",
             note="64-bit datapath: W forms only benefit via early-out on smaller magnitudes",
             src=s("div_unit")),
        dict(cls="load_int", insns="ld/lw/lwu/lh/lhu/lb/lbu (L1 hit)", gcc_types="load",
             ports=memp, latency=ISSUE_TO_EX + 1 + SLOW_WAKEUP, recip_thpt=1 / len(memp), basis="derived",
             note="speculative wakeup from DCache s1; misses replay (poison)",
             src=s("maddr_comb", "mem_incoming", "spec_ld_wakeup")),
        dict(cls="load_fp", insns="fld/flw (L1 hit)", gcc_types="fpload",
             ports=memp, latency=ISSUE_TO_EX + 2 + SLOW_WAKEUP, recip_thpt=1 / len(memp), basis="derived",
             note="no speculative wakeup for FP loads (wakeup at s2 writeback)",
             src=s("spec_ld_not_fp", "fp_wakeup")),
        dict(cls="store_int", insns="sd/sw/sh/sb", gcc_types="store",
             ports=memp, latency=None, recip_thpt=1 / len(memp), basis="derived",
             note="single STA uop (addr+data) from the mem issue queue",
             src=[model["decode"]["SD"]["src"]]),
        dict(cls="store_fp", insns="fsd/fsw", gcc_types="fpstore",
             ports=memp + f2ip, latency=None, recip_thpt=1.0, basis="derived",
             note="split: STA on a mem port + data via FPIU on fp0 (shares fp0 with fdiv/F2I)",
             src=[model["decode"]["FSD"]["src"]]),
        dict(cls="fp_fma", insns="fadd/fsub/fmul/fmadd/fmsub/fnm*/fsgnj/fmin/fmax/fcvt.s.d", gcc_types="fadd,fmul,fmadd,fmove,fcvt",
             ports=fpp, latency=ISSUE_TO_EX + dfma + SLOW_WAKEUP, recip_thpt=1 / len(fpp), basis="derived",
             note="FP has no bypass network; all FPU ops padded to dfmaLatency",
             src=s("fpu_pad", "fpu_unit_stages", "fp_wakeup")),
        dict(cls="fp_to_int", insns="fmv.x.d/fcvt.l.d/feq/flt/fle/fclass", gcc_types="mfc,fcmp,fcvt_f2i",
             ports=f2ip, latency=ISSUE_TO_EX + dfma + 1 + SLOW_WAKEUP, recip_thpt="~1-2", basis="estimate",
             note="FPIU result queued then arbitrated into the int long-latency write port; F2I issue masked while queue non-empty",
             src=s("fpu_pad")),
        dict(cls="int_to_fp", insns="fmv.d.x/fcvt.d.l/fcvt.s.w", gcc_types="mtc,fcvt_i2f",
             ports=port_of("I2F"), latency=ISSUE_TO_EX + i2f + 1 + SLOW_WAKEUP, recip_thpt="~1-2", basis="estimate",
             note="IFPU on integer port int0 (shared with JMP), result queued to FP ll write port",
             src=s("ifpu")),
        dict(cls="fdiv", insns="fdiv.d/fdiv.s", gcc_types="fdiv",
             ports=fdivp, latency=ISSUE_TO_EX + 1 + hf_div + 1 + SLOW_WAKEUP, recip_thpt=hf_div + 1,
             basis="unit-RTL (DivSqrtRecF64 fire->out 18) + derived",
             note="single precision is up-converted and runs the double algorithm",
             src=s("fdiv_hw", "fdiv_one")),
        dict(cls="fsqrt", insns="fsqrt.d/fsqrt.s", gcc_types="fsqrt",
             ports=fdivp, latency=ISSUE_TO_EX + 1 + hf_sqrt + 1 + SLOW_WAKEUP, recip_thpt=hf_sqrt + 1,
             basis="unit-RTL (DivSqrtRecF64 fire->out 26) + derived",
             src=s("fdiv_hw", "fdiv_one")),
        dict(cls="branch_mispredict_penalty", insns="-", gcc_types="(branch_cost)",
             ports=[], latency="~13 (>=12)", recip_thpt=None, basis="estimate",
             note="static stage count: EX resolve -> b2 reg -> redirect -> F0..F4 -> fetch buffer -> decode/ren1 -> ren2/dispatch -> IQ -> issue -> RR -> EX",
             src=s("br_b2")),
    ]
    return rows, {"hf_div_core": hf_div, "hf_sqrt_core": hf_sqrt}
