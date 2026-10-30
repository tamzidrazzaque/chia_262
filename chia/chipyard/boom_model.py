"""Experimental MegaBOOM V3 GCC tuning; source-derived seeds, not calibration.

Target source: riscv-boom/riscv-boom 5223e44cfeb26f41380057a2eb4d651197475f69,
src/main/scala/v3/common/{config-mixins,parameters}.scala. The GCC machine
description syntax follows the pinned compiler's generic.md. No external code
is copied here. GCC costs are heuristics, not a literal cycle-count model.
"""

import re

MODEL_VERSION = "megaboom-v3-experimental-v1"
SOURCE_REVISION = "5223e44cfeb26f41380057a2eb4d651197475f69"
SOURCE_SEED_COSTS = {"fp_add": [4, 4], "fp_mul": [4, 4], "fp_div": [20, 20],
              "int_mul": [3, 3], "int_div": [6, 6], "branch_cost": 3,
              "memory_cost": 5, "fmv_cost": 8}
# Paired F2 kernel ablation: cost3 chose multiply for constants 11/13 and
# regressed; cost4 recovered shift/add code. GCC heuristic cost != latency.
# Preserve the original seed for reproducibility; scheduler multiply stays 3.
SEED_COSTS = {**SOURCE_SEED_COSTS, "int_mul": [4, 4]}
ASSUMPTIONS = {
    "source_derived": {"decode_width": 4, "integer_issue_width": 4,
                       "memory_issue_width": 2, "fp_issue_width": 2,
                       "integer_multiply_latency": 3, "fp_fma_latency": 4},
    "uncalibrated": ["load-use latency 3", "integer divide latency 34/66",
                     "FP divide/sqrt latency 20/25", "branch and memory costs",
                     "FP transfer costs", "pooled execution ports and cache effects"],
    "interpretation": "Compiler scheduling approximation; validate on matching F2 before selection",
}


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError("pinned GCC source shape differs")
    return text.replace(old, new)


MOVE_FIELDS = {"gpr_to_fpr", "fpr_to_gpr", "gpr_load", "gpr_store", "fpr_load", "fpr_store"}
MOVE_PROFILE_VERSION = "directional-register-and-spill-costs-v1"


def validate_move_profile(profile):
    if not isinstance(profile, dict) or profile.keys() != MOVE_FIELDS or any(
            type(value) is not int or not 1 <= value <= 32 for value in profile.values()):
        raise ValueError("move profile requires exactly six bounded integer costs (1..32)")
    return profile


def render_move_profile(cc, profile):
    """Expose directional register and register-class spill costs on BOOM only."""
    p = validate_move_profile(profile)
    start = "  if ((from == FP_REGS && to == GR_REGS) ||"
    hook = ("  if (tune_param == &boom_tune_info)\n    {\n"
            f"      if (from == GR_REGS && to == FP_REGS) return {p['gpr_to_fpr']};\n"
            f"      if (from == FP_REGS && to == GR_REGS) return {p['fpr_to_gpr']};\n"
            "    }\n\n")
    cc = replace_once(cc, start, hook + start)
    start = "  return (tune_param->memory_cost\n\t  + memory_move_secondary_cost (mode, rclass, in));"
    hook = ("  if (tune_param == &boom_tune_info)\n    {\n"
            "      int cost = 0;\n"
            f"      if (reg_class_subset_p (rclass, GR_REGS)) cost = in ? {p['gpr_load']} : {p['gpr_store']};\n"
            f"      else if (reg_class_subset_p (rclass, FP_REGS)) cost = in ? {p['fpr_load']} : {p['fpr_store']};\n"
            "      if (cost) return cost + memory_move_secondary_cost (mode, rclass, in);\n"
            "    }\n\n")
    return replace_once(cc, start, hook + start)


def render_sources(originals: dict, costs: dict, issue_rate: int = 4, move_profile=None) -> dict:
    """Add a separate tune table and scheduling automaton; keep Rocket intact."""
    from chia.chipyard.cost_model import render_costs, render_scheduling, validate_scheduling
    validate_scheduling({"issue_rate": issue_rate})
    cc = originals["riscv.cc"]
    tuned = render_scheduling(render_costs(cc, costs), {"issue_rate": issue_rate})
    table = re.search(r"static const struct riscv_tune_param rocket_tune_info = \{.*?\n\};", tuned, re.S)
    if table is None:
        raise ValueError("pinned Rocket table missing")
    boom = table[0].replace("rocket_tune_info", "boom_tune_info", 1)
    cc = replace_once(cc, "/* A table describing all the processors GCC knows about.  */",
                      boom + "\n\n/* A table describing all the processors GCC knows about.  */")
    if move_profile is not None:
        cc = render_move_profile(cc, move_profile)
    cores = replace_once(originals["riscv-cores.def"], '\n#undef RISCV_TUNE',
                         '\nRISCV_TUNE("boom", boom, boom_tune_info)\n\n#undef RISCV_TUNE')
    opts = replace_once(originals["riscv-opts.h"], "  generic,\n  sifive_7\n",
                         "  generic,\n  sifive_7,\n  boom\n")
    md = replace_once(originals["riscv.md"], '"generic,sifive_7"', '"generic,sifive_7,boom"')
    md += '\n(include "boom.md")\n'
    return {"riscv.cc": cc, "riscv-cores.def": cores, "riscv-opts.h": opts,
            "riscv.md": md, "boom.md": scheduling_description()}


def scheduling_description() -> str:
    """A bounded approximation, intentionally separate from the generic DFA."""
    result = [';; Experimental MegaBOOM V3 scheduling; see boom_model.py assumptions.',
              '(define_automaton "boom_pipe")']
    for name in ["alu0", "alu1", "alu2", "alu3", "mem0", "mem1", "fp0", "fp1", "mul", "div", "fdiv"]:
        result.append(f'(define_cpu_unit "boom_{name}" "boom_pipe")')
    alu = "(boom_alu0|boom_alu1|boom_alu2|boom_alu3)"
    mem = "(boom_mem0|boom_mem1)"
    fp = "(boom_fp0|boom_fp1)"
    groups = [
        ("alu", 1, "unknown,const,arith,shift,slt,multi,auipc,nop,logical,move", alu),
        ("branch", 1, "branch,jump,call", "boom_alu0"),
        ("load", 3, "load,fpload", mem),
        ("store", 1, "store,fpstore", mem),
        ("xfer", 3, "mfc,mtc,fcvt,fmove,fcmp", fp),
        ("imul", 3, "imul", f"{alu}+boom_mul"),
        ("fp", 4, "fadd,fmul,fmadd", fp),
        ("fdiv", 20, "fdiv", f"{fp}+boom_fdiv,boom_fdiv*19"),
        ("fsqrt", 25, "fsqrt", f"{fp}+boom_fdiv,boom_fdiv*24"),
    ]
    for name, latency, types, resource in groups:
        result.append(f'(define_insn_reservation "boom_{name}" {latency}\n'
                      f'  (and (eq_attr "tune" "boom") (eq_attr "type" "{types}"))\n  "{resource}")')
    for mode, latency in [("SI", 34), ("DI", 66)]:
        result.append(f'(define_insn_reservation "boom_idiv_{mode.lower()}" {latency}\n'
                      f'  (and (eq_attr "tune" "boom") (and (eq_attr "type" "idiv") '
                      f'(eq_attr "mode" "{mode}")))\n'
                      f'  "{alu}+boom_div,boom_div*{latency - 1}")')
    return "\n\n".join(result) + "\n"
