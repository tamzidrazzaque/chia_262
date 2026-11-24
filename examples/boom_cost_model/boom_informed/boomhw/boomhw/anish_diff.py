"""Diff the RTL-derived model against the hand-written MegaBOOM tune in
CHIA origin/main chia/chipyard/boom_model.py (SEED_COSTS + scheduling_description)."""
import re
import subprocess

from . import timing
from . import muldiv_model as mdm
from .gcc_gen import dfa_values


def load_anish(repo, ref="origin/main", path="chia/chipyard/boom_model.py"):
    text = subprocess.run(["git", "-C", repo, "show", f"{ref}:{path}"], check=True,
                          capture_output=True, text=True).stdout
    commit = subprocess.run(["git", "-C", repo, "log", "-1", "--format=%H", ref, "--", path],
                            check=True, capture_output=True, text=True).stdout.strip()
    return text, commit


def evaluate_anish(text):
    """Execute only the module body (constants + pure functions; it imports
    only `re` at top level) and call scheduling_description()."""
    ns = {"__name__": "anish_boom_model"}
    exec(compile(text, "boom_model.py", "exec"), ns)  # team source, read-only use
    return {"SEED_COSTS": ns["SEED_COSTS"], "SOURCE_SEED_COSTS": ns["SOURCE_SEED_COSTS"],
            "ASSUMPTIONS": ns["ASSUMPTIONS"], "md": ns["scheduling_description"](),
            "SOURCE_REVISION": ns.get("SOURCE_REVISION")}


RESV = re.compile(r'\(define_insn_reservation "(\w+)" (\d+)\s*\(and \(eq_attr "tune" "\w+"\)\s*'
                  r'(?:\(and )?\(eq_attr "type" "([^"]+)"\)\s*(?:\(eq_attr "mode" "(\w+)"\)\)?)?\)?\)\s*"([^"]+)"\)', re.S)


def parse_md(md):
    out = []
    for m in RESV.finditer(md):
        out.append({"name": m.group(1), "latency": int(m.group(2)),
                    "types": [t.strip() for t in m.group(3).split(",")],
                    "mode": m.group(4), "resources": m.group(5)})
    return out


def type_index(resvs):
    idx = {}
    for r in resvs:
        for t in r["types"]:
            key = t + (":" + r["mode"] if r["mode"] else "")
            idx[key] = r
    return idx


def diff(model, anish, gcc_types=None):
    A = parse_md(anish["md"])
    ai = type_index(A)
    v = dfa_values(model)
    rows, _ = timing.class_table(model)
    by = {r["cls"]: r for r in rows}
    anc = model["anchors"]
    seed = anish["SEED_COSTS"]
    D = []

    def add(topic, anish_val, rtl_val, verdict, evidence, impact):
        D.append({"topic": topic, "anish": anish_val, "rtl_model": rtl_val, "verdict": verdict,
                  "evidence": evidence if isinstance(evidence, list) else [evidence], "compiler_impact": impact})

    # ---- divider --------------------------------------------------------
    di = ai.get("idiv:DI")
    si = ai.get("idiv:SI")
    add("idiv port / ALU blocking",
        f"{di['resources']} (any pooled ALU + boom_div)" if di else None,
        "issues only on int3 (is_nth(3)); occupies int3's issue slot 1 cycle; ALU ops keep issuing on int3 "
        "while MulDiv iterates (only the FU_DIV bit of fu_types is masked)",
        "partly wrong: div is pinned to int3 (not any ALU); it does not block any ALU beyond its issue cycle",
        [anc["div_fu_types"]["src"], anc["div_busy"]["src"]] + model["exec_ports"]["int"][3]["src"][-1:],
        "small: pooled-ALU reservation lets the scheduler place two divs' issue cycles freely; real constraint is one divider")
    add("mul vs div port", "separate boom_mul / boom_div units, imul pooled over any ALU",
        "IMUL on int2 only, IDIV on int3 only (different ports); mulh* also IMUL",
        "units separate = correct; imul pooled across ALUs = wrong (int2 only, 1/cycle)",
        model["exec_ports"]["int"][2]["src"][-1:] + [model["decode"]["MULHU"]["src"]],
        "low (one mul/cycle either way); matters for mul-heavy blocks: at most one mul issues per cycle")
    full = timing.div_core_latency(mdm.FN_DIVU, 1, 0xF123_4567_89AB_CDEF, 10)
    add("idiv DI latency", di["latency"] if di else None,
        {"full_width_div_small_const": full, "range": "7..71", "x_div_1_x_ge_2^63": timing.div_core_latency(5, 1, 1 << 63, 1),
         "quotient_zero_5_div_13": timing.div_core_latency(5, 1, 5, 13),
         "best_equal_msb": timing.div_core_latency(5, 1, 1000, 600)},
        "66 ~= the full-width-dividend/small-divisor case (MulDiv 64 cycles + 3 pipeline); "
        "but hardware is strongly operand-dependent via divEarlyOut",
        [model["muldiv_params"]["divEarlyOut"]["src"][0], anc["div_unit"]["src"]],
        "DFA value is a reasonable single point for 64-bit dividends; wrong for small values (as low as 7)")
    add("idiv SI latency", si["latency"] if si else None,
        {"divw_full_31bit_div_10": timing.div_core_latency(mdm.FN_DIV, 0, 0x7123_4567, 10), "range": "7..71"},
        "W forms run on the same 64-bit MulDiv (DivUnit(xLen)); SI is cheaper only because 32-bit magnitudes "
        f"early-out sooner. {si['latency'] if si else None} vs {timing.div_core_latency(mdm.FN_DIV, 0, 0x7123_4567, 10)} "
        "for the full-31-bit/small-divisor case",
        [anc["div_unit"]["src"]], "consistent for full 32-bit dividends")
    add("divider early-out", "not modelled (fixed 34/66; identical to GCC generic.md idivsi/idivdi)",
        "MulDiv(divEarlyOut=true, divUnroll=1): cycles = 1 + neg_in + N + neg_out, N = 3 + (msb(a)-msb(b)) "
        "when msb(a)>=msb(b); N = 65 when b=0, when msb(a)-msb(b)=63, or when msb(a)+1 == msb(b); "
        "N = 67-(msb(b)-msb(a)) when msb(a)<msb(b) (6-bit wrap: quotient-0 divides are SLOW)",
        "missing", [model["muldiv_params"]["divEarlyOut"]["src"][0]] + ["generators/rocket-chip/src/main/scala/rocket/Multiplier.scala:147-157"],
        "small-operand divides are much cheaper (7-20 cycles) but x/y with x<y and 0/y are worst-case (~69)")
    add("int_div cost (SEED_COSTS)", seed.get("int_div"),
        {"SI": v["idiv_si"], "DI": v["idiv_di"]},
        f"far too low: COSTS_N_INSNS({seed.get('int_div')}) vs {v['idiv_si']}/{v['idiv_di']}-cycle hardware "
        "(full-width dividend). GCC only emits the multiply-high sequence for x/const while its cost stays "
        "below the div cost, so a 6-insn div cost risks keeping hardware div where mulh+shift(+sign fix) "
        "(~8 cycles dependent) is several times faster",
        [anc["div_unit"]["src"], "gcc/expmed.cc:4408 (max_cost = udiv/sdiv_cost), gcc/expmed.cc:4539,4571 (max_cost - extra_cost)",
         "gcc/config/riscv/riscv.cc:4305 (*total = tune_param->int_div[mode == DImode])"],
        "high: const-division expansion decisions (expand_divmod cost check)")
    # ---- multiplier -----------------------------------------------------
    im = ai.get("imul")
    add("imul scheduling latency", im["latency"] if im else None, by["imul"]["latency"],
        "too low by 3: imulLatency=3 is the multiplier depth, but MUL is not bypassable; dependents wake "
        "from writeback: 2 (issue->EX) + 3 + 1 = 6",
        by["imul"]["src"], "medium: scheduler under-separates mul->use; affects mul chains, mulh-based const div")
    add("int_mul cost (SEED_COSTS)", seed.get("int_mul"), by["imul"]["latency"],
        "direction agrees with Anish's F2 ablation (cost 4 beat 3); RTL says 6 cycles latency / 1 per cycle",
        by["imul"]["src"], "synth_mult: shift/add sequences up to ~5-6 ALU ops (4-wide) beat a dependent mul")
    # ---- loads ----------------------------------------------------------
    ld = ai.get("load")
    add("load-use latency", ld["latency"] if ld else None,
        {"int": by["load_int"]["latency"], "fp": by["load_fp"]["latency"]},
        "int load-use is 4 (spec wakeup at s1 -> issue at s2), FP loads 5 (no spec wakeup)",
        by["load_int"]["src"] + by["load_fp"]["src"], "medium for pointer chasing / FP streams")
    # ---- branches / jumps -----------------------------------------------
    br = ai.get("branch")
    add("branch port", br["resources"] if br else None,
        "conditional branches (FU_ALU) on any of int0..int3; only jal/jalr/auipc (FU_JMP) are int0-only",
        "wrong: models one branch per cycle", [model["decode"]["BEQ"]["src"], model["decode"]["JALR"]["src"]],
        "low-medium: branchy unrolled code can resolve up to 4 branches/cycle")
    au = ai.get("auipc")
    add("auipc latency", au["latency"] if au else None, by["auipc"]["latency"],
        "auipc is FU_JMP (int0 only) and not bypassable -> 4-cycle latency, not 1",
        [model["decode"]["AUIPC"]["src"]], "low: address formation (medany / PIC / calls)")
    # ---- FP -------------------------------------------------------------
    fp = ai.get("fadd")
    add("FP add/mul/fma latency", fp["latency"] if fp else None, by["fp_fma"]["latency"],
        "dfmaLatency=4 is the pipe depth; FP results wake dependents at writeback -> 7",
        by["fp_fma"]["src"], "medium for FP reductions; SEED fp_add/fp_mul [4,4] likewise under-states")
    xf = ai.get("mfc")
    add("int<->FP transfer", f"{xf['latency']} on {xf['resources']}" if xf else None,
        {"fp_to_int (fp0 only)": by["fp_to_int"]["latency"], "int_to_fp (int0 IFPU)": by["int_to_fp"]["latency"]},
        "mtc/fcvt_i2f execute on INTEGER port int0, not an FP port; mfc/fcmp/fcvt_f2i only on fp0",
        by["fp_to_int"]["src"] + by["int_to_fp"]["src"], "low-medium (estimates; validate)")
    fd = ai.get("fdiv")
    add("fdiv/fsqrt latency", {"fdiv": fd["latency"] if fd else None, "fsqrt": ai.get("fsqrt", {}).get("latency")},
        {"fdiv": by["fdiv"]["latency"], "fsqrt": by["fsqrt"]["latency"],
         "occupancy": {"fdiv": by["fdiv"]["recip_thpt"], "fsqrt": by["fsqrt"]["recip_thpt"]}},
        "hardfloat DivSqrtRecF64: 18 / 26 cycles in the unit (Verilator), +5 core; fdiv only on fp0",
        by["fdiv"]["src"], "low")
    fs = ai.get("fpstore")
    add("FP store resources", fs["resources"] if fs else None, "mem port + fp0 (store data via FPIU)",
        "FP stores also consume fp0", [model["decode"]["FSD"]["src"]], "low")
    # ---- coverage -------------------------------------------------------
    if gcc_types:
        covered = set(ai_t.split(":")[0] for ai_t in ai)
        missing = [t for t in gcc_types if t not in covered and t != "ghost" and not t.startswith("v")
                   and not t.startswith("sf_")]
        add("DFA type coverage vs GCC 15.1 riscv.md", f"missing scalar types: {missing}",
            "generated DFA covers every type", "Anish's DFA targets CHIA's pinned GCC (c891d8dc); on GCC 15 "
            "types like jalr/ret/fcvt_i2f/fcvt_f2i/atomic/trap would hit gcc_assert(insn_has_dfa_reservation_p)",
            ["gcc/config/riscv/riscv.cc:9879 (GCC 15.1 g1b306039a)"], "only if the DFA is ported to GCC 15")
    return D
