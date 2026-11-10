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
POLICY_VERSION = "pressure-growth-defaults-v1"
GROWTH_PRESETS = {"default": None, "compact": (64, 1), "tight": (32, 1),
                  "relaxed": (128, 1), "peel_only": (64, 4), "jam_only": (200, 1),
                  "inline": (64, 1), "unroll": (64, 1), "inline_unroll": (64, 1)}
# Larger code-generation interventions retain the confirmed pressure/peel policy.
# These are experimental target defaults, not calibrated hardware latencies.
INLINE_DEFAULTS = {"param_max_inline_insns_auto": 180, "param_inline_unit_growth": 80}
UNROLL_DEFAULTS = {"flag_unroll_loops": 1, "param_max_unrolled_insns": 256,
                   "param_max_average_unrolled_insns": 128}
EXTRA_POLICY_DEFAULTS = {"inline": INLINE_DEFAULTS, "unroll": UNROLL_DEFAULTS,
                         "inline_unroll": {**INLINE_DEFAULTS, **UNROLL_DEFAULTS}}

# A wider structural experiment around the confirmed ordinary-unroll policy.
# Limits are GCC instruction-cost budgets, not literal unroll factors or bytes.
STRUCTURAL_DEFAULTS = {
    'unroll_small': (128, 64, None, None),
    'unroll_large': (512, 256, None, None),
    'unroll_xlarge': (1024, 512, None, None),
    'inline_selective': (256, 128, 80, 30),
    'inline_selective_large': (512, 256, 80, 30),
    'inline_small_large': (512, 256, 20, 10),
    'inline_selective_xlarge': (1024, 512, 80, 30),
    'inline_small_small': (128, 64, 20, 10),
}
for _name, (_maximum, _average, _inline, _growth) in STRUCTURAL_DEFAULTS.items():
    GROWTH_PRESETS[_name] = (64, 1)
    EXTRA_POLICY_DEFAULTS[_name] = {'flag_unroll_loops': 1,
        'param_max_unrolled_insns': _maximum, 'param_max_average_unrolled_insns': _average}
    if _inline is not None:
        EXTRA_POLICY_DEFAULTS[_name].update(param_max_inline_insns_auto=_inline,
            param_inline_unit_growth=_growth)

# Independent pass ablations inherit the exact loop/inlining anchor. Existing
# names keep their source fragments and compiler identities unchanged.
for _base in tuple(GROWTH_PRESETS):
    for _suffix, _option, _value in [('no_presched', 'flag_schedule_insns', 0),
                                     ('tracer', 'flag_tracer', 1)]:
        _name = _base + '_' + _suffix
        GROWTH_PRESETS[_name] = GROWTH_PRESETS[_base]
        EXTRA_POLICY_DEFAULTS[_name] = {**EXTRA_POLICY_DEFAULTS.get(_base, {}),
                                      _option: _value}

# New structural tests inherit the existing anchor without changing historical
# fragments or identities. IRA enum tokens come from pinned GCC common.opt.
PORTFOLIO_DEFAULTS = {
    'shrink_live': {'flag_live_range_shrinkage': 1},
    'ira_all': {'flag_ira_region': 'IRA_REGION_ALL'},
    'unswitch_large': {'param_max_unswitch_insns': 400},
    'no_unswitch': {'flag_unswitch_loops': 0},
    'no_clone': {'flag_ipa_cp_clone': 0},
}
for _name, _parts in {
        'ira_all_shrink': ('ira_all', 'shrink_live'),
        'unswitch_large_shrink': ('unswitch_large', 'shrink_live'),
        'no_clone_ira_all': ('no_clone', 'ira_all'),
        'no_clone_shrink': ('no_clone', 'shrink_live')}.items():
    PORTFOLIO_DEFAULTS[_name] = {key: value for part in _parts
                               for key, value in PORTFOLIO_DEFAULTS[part].items()}
for _base in ('unroll', *STRUCTURAL_DEFAULTS):
    for _suffix, _options in PORTFOLIO_DEFAULTS.items():
        _name = _base + '_' + _suffix
        GROWTH_PRESETS[_name] = GROWTH_PRESETS[_base]
        EXTRA_POLICY_DEFAULTS[_name] = {**EXTRA_POLICY_DEFAULTS[_base], **_options}


def validate_policy(policy):
    """Bound the BOOM-only scheduling/allocation and loop-growth experiment."""
    fields = {"pressure_algorithm", "ira_loop_pressure", "growth_budget"}
    if not isinstance(policy, dict) or policy.keys() != fields:
        raise ValueError("policy requires pressure_algorithm, ira_loop_pressure, growth_budget")
    if type(policy["pressure_algorithm"]) is not int or policy["pressure_algorithm"] not in (0, 1, 2):
        raise ValueError("pressure_algorithm must be 0, 1 or 2")
    if type(policy["ira_loop_pressure"]) is not bool:
        raise ValueError("ira_loop_pressure must be boolean")
    if not isinstance(policy["growth_budget"], str) or policy["growth_budget"] not in GROWTH_PRESETS:
        raise ValueError("growth_budget must be a bounded named preset")
    return policy


def normalize_policy(policy):
    """An identity policy reuses the exact historical compiler snapshot."""
    if policy is None:
        return None
    validate_policy(policy)
    if policy == {"pressure_algorithm": 0, "ira_loop_pressure": False, "growth_budget": "default"}:
        return None
    return policy


def policy_fragment(policy):
    """Set experimental target defaults while preserving explicit user options."""
    policy = normalize_policy(policy)
    if policy is None:
        return ""
    settings = []
    if policy["pressure_algorithm"]:
        settings += [("flag_sched_pressure", 1), ("param_sched_pressure_algorithm", policy["pressure_algorithm"])]
    if policy["ira_loop_pressure"]:
        settings += [("flag_ira_loop_pressure", 1)]
    growth = GROWTH_PRESETS[policy["growth_budget"]]
    if growth is not None:
        settings += [("param_max_completely_peeled_insns", growth[0]), ("param_unroll_jam_max_unroll", growth[1])]
    settings += list(EXTRA_POLICY_DEFAULTS.get(policy['growth_budget'], {}).items())
    return ("\n  /* Experimental BOOM pressure/growth defaults; explicit options win.  */\n"
            "  if (tune_param == &boom_tune_info)\n    {\n"
            + "".join(f"      SET_OPTION_IF_UNSET (&global_options, &global_options_set, {key}, {value});\n"
                      for key, value in settings) + "    }\n")


def render_policy(cc, policy):
    anchor = "  tune_param = optimize_size ? &optimize_size_tune_info : cpu->tune_param;\n"
    return replace_once(cc, anchor, anchor + policy_fragment(policy))


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


def render_sources(originals: dict, costs: dict, issue_rate: int = 4, move_profile=None, policy=None) -> dict:
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
    if normalize_policy(policy) is not None:
        cc = render_policy(cc, policy)
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
