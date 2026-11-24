#!/usr/bin/env python3
"""Render BOOM tune variants onto pristine GCC 15.1 (g1b306039a) riscv sources.

Variants (all share Anish's non-latency policy, move profile and table structure):
  A anish-boom      : Anish origin/main boom_model.py (7ea95502 winner settings), DFA = his
                      scheduling_description() + GCC-15 type coverage (closest of his groups).
  B rtl-boom        : same table/policy, latency costs from rtl-model tune_suggestion.json,
                      DFA = rtl-model out/boom.md.
  C anish-intdiv    : A with only int_div -> 34/67.
  D rtl-boom-mul3  : B with int_mul cost back to Anish's [3,3] (isolates synth_mult cost from DFA)
  E rtl-boom-divmod: B + use_divmod_expansion=true (rtl-model suggestion)

Anish's render_sources() targets GCC c891d8dc; four anchors differ on 15.1
(riscv-opts.h enum, riscv.md tune attr, option-override anchor, register-move-cost
anchor). This module re-implements exactly those four edits with 15.1 anchors and
reuses his code for everything else (cost regex, policy_fragment, scheduling_description).
"""
import argparse, hashlib, json, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE / "anish_src"))
from chia.chipyard import boom_model  # noqa: E402  (Anish origin/main bc3f711a)

# Anish's confirmed winner, compiler 7ea95502... (progress-20261103.json, followup round, index 3)
ANISH_WINNER = {
    "costs": {"fp_add": [4, 4], "fp_mul": [4, 4], "fp_div": [20, 20], "int_mul": [3, 3],
              "int_div": [6, 6], "branch_cost": 12, "memory_cost": 7, "fmv_cost": 16},
    "move_profile": {"gpr_to_fpr": 16, "fpr_to_gpr": 16, "gpr_load": 8, "gpr_store": 6,
                     "fpr_load": 10, "fpr_store": 8},
    "policy": {"pressure_algorithm": 2, "ira_loop_pressure": True, "growth_budget": "unroll"},
    "issue_rate": 4,
}
LATENCY_KEYS = ("fp_add", "fp_mul", "fp_div", "int_mul", "int_div")

# GCC 15.1 types absent from Anish's DFA (it targets c891d8dc). Without a reservation
# riscv_sched_variable_issue hits gcc_assert(insn_has_dfa_reservation_p). Mapped to the
# closest of HIS groups; these are additions, his reservations stay byte-identical.
A_GCC15_EXTRA = [
    ("g15_alu", 1, "sfb_alu,bitmanip,rotate,clmul,min,max,minu,maxu,clz,ctz,cpop,condmove,crypto,"
                   "mvpair,zicond,trap,rdvlenb,rdvl,wrvxrm,wrfrm,rdfrm",
     "(boom_alu0|boom_alu1|boom_alu2|boom_alu3)"),           # like his "alu"
    ("g15_branch", 1, "jalr,ret", "boom_alu0"),               # like his "branch" (jump,call)
    ("g15_xfer", 3, "fcvt_i2f,fcvt_f2i", "(boom_fp0|boom_fp1)"),  # like his "xfer" (fcvt)
    ("g15_atomic", 3, "atomic", "(boom_mem0|boom_mem1)"),     # like his "load"
]


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f"anchor count {text.count(old)} != 1: {old[:60]!r}")
    return text.replace(old, new)


def render_costs_unbounded(original, values):
    """Anish's cost_model.render_costs regex without its 1..64 bound (int_div DI=67)."""
    pat = r"(static const struct riscv_tune_param rocket_tune_info = \{)(.*?)(\n\};)"
    m = re.search(pat, original, re.S)
    body = m[2]
    for key, value in values.items():
        rep = ("{" + ", ".join(f"COSTS_N_INSNS ({v})" for v in value) + "}"
               if isinstance(value, list) else str(value))
        body, n = re.subn(r"(?m)^[ \t]*[^\n]+?(,\s*/\* " + key + r" \*/)", lambda mm: "  " + rep + mm[1], body)
        assert n == 1, key
    return original[:m.start(2)] + body + original[m.end(2):]


def set_bool_field(table, field, value):
    table, n = re.subn(r"(?m)^[ \t]*(true|false)(,\s*/\* " + field + r" \*/)",
                       lambda mm: "  " + value + mm[2], table)
    assert n == 1, field
    return table


def vector_types(md):
    m = re.search(r'\(define_attr "type"\s*"(.*?)"', md, re.S)
    types = [t.strip() for t in m[1].replace("\n", " ").split(",") if t.strip()]
    return types


def anish_dfa_gcc15(md_text):
    d = boom_model.scheduling_description()
    covered = set()
    for t in re.findall(r'eq_attr "type" "([^"]*)"', d):
        covered |= {x.strip() for x in t.split(",")}
    extra = []
    for name, lat, types, res in A_GCC15_EXTRA:
        covered |= set(types.split(","))
        extra.append((name, lat, types, res))
    rest = [t for t in vector_types(md_text) if t not in covered and t != "ghost"]
    # vector types: unreachable at rv64gc; covered for completeness like rtl-model's boom_unsupported
    extra.append(("g15_unsupported", 1, ",".join(rest), "boom_alu0"))
    out = [d.rstrip("\n"), ";; GCC 15.1 coverage additions (rtl-tune/scripts/render15.py); "
                           "not part of Anish's model"]
    for name, lat, types, res in extra:
        out.append(f'(define_insn_reservation "boom_{name}" {lat}\n'
                   f'  (and (eq_attr "tune" "boom") (eq_attr "type" "{types}"))\n  "{res}")')
    return "\n\n".join(out) + "\n"


def render(pristine, costs, dfa, move_profile, policy, issue_rate=4, divmod=None):
    cc = pristine["riscv.cc"]
    tuned = render_costs_unbounded(cc, costs)
    # Anish's render_scheduling (issue_rate) via the same regex
    tuned, n = re.subn(r"(?m)^[ \t]*\d+(,\s*/\* issue_rate \*/)", lambda m: f"  {issue_rate}" + m[1], tuned, count=0)
    table = re.search(r"static const struct riscv_tune_param rocket_tune_info = \{.*?\n\};", tuned, re.S)[0]
    boom = table.replace("rocket_tune_info", "boom_tune_info", 1)
    if divmod is not None:
        boom = set_bool_field(boom, "use_divmod_expansion", divmod)
    cc = replace_once(cc, "/* A table describing all the processors GCC knows about.  */",
                      boom + "\n\n/* A table describing all the processors GCC knows about.  */")
    p = boom_model.validate_move_profile(move_profile)
    # register move cost: 15.1 anchor (his: "  if ((from == FP_REGS && to == GR_REGS) ||")
    start = "  if ((from_is_fpr && to_is_gpr) || (from_is_gpr && to_is_fpr))\n    return tune_param->fmv_cost;"
    hook = ("  if (tune_param == &boom_tune_info)\n    {\n"
            f"      if (from == GR_REGS && to == FP_REGS) return {p['gpr_to_fpr']};\n"
            f"      if (from == FP_REGS && to == GR_REGS) return {p['fpr_to_gpr']};\n"
            "    }\n\n")
    cc = replace_once(cc, start, hook + start)
    # memory move cost: same anchor as his, but 15.1 indents the continuation with a tab
    start = "  return (tune_param->memory_cost\n\t  + memory_move_secondary_cost (mode, rclass, in));"
    hook = ("  if (tune_param == &boom_tune_info)\n    {\n"
            "      int cost = 0;\n"
            f"      if (reg_class_subset_p (rclass, GR_REGS)) cost = in ? {p['gpr_load']} : {p['gpr_store']};\n"
            f"      else if (reg_class_subset_p (rclass, FP_REGS)) cost = in ? {p['fpr_load']} : {p['fpr_store']};\n"
            "      if (cost) return cost + memory_move_secondary_cost (mode, rclass, in);\n"
            "    }\n\n")
    cc = replace_once(cc, start, hook + start)
    # policy: his fragment verbatim, after tune_param is set for the global options
    anchor = "  riscv_override_options_internal (&global_options);\n"
    cc = replace_once(cc, anchor, anchor + boom_model.policy_fragment(policy))
    cores = replace_once(pristine["riscv-cores.def"], "\n#undef RISCV_TUNE",
                         '\nRISCV_TUNE("boom", boom, boom_tune_info)\n\n#undef RISCV_TUNE')
    opts = replace_once(pristine["riscv-opts.h"], "  generic_ooo\n};", "  generic_ooo,\n  boom\n};")
    md = replace_once(pristine["riscv.md"], '"generic,sifive_7,sifive_p400,sifive_p600,xiangshan,generic_ooo"',
                      '"generic,sifive_7,sifive_p400,sifive_p600,xiangshan,generic_ooo,boom"')
    md += '\n(include "boom.md")\n'
    return {"riscv.cc": cc, "riscv-cores.def": cores, "riscv-opts.h": opts, "riscv.md": md, "boom.md": dfa}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pristine", required=True, help="pristine gcc/config/riscv dir")
    ap.add_argument("--rtl-model", required=True, help="rtl-model/out dir")
    ap.add_argument("--variant", required=True, choices=["A", "B", "C", "D", "E"])
    ap.add_argument("--out", required=True, help="gcc/config/riscv dir of the variant source tree")
    a = ap.parse_args()
    names = ["riscv.cc", "riscv-cores.def", "riscv-opts.h", "riscv.md"]
    pristine = {n: (Path(a.pristine) / n).read_text() for n in names}
    rtl = json.loads((Path(a.rtl_model) / "tune_suggestion.json").read_text())
    costs = dict(ANISH_WINNER["costs"])
    divmod = None
    if a.variant == "A":
        dfa = anish_dfa_gcc15(pristine["riscv.md"])
    elif a.variant in ("B", "D", "E"):
        for k in LATENCY_KEYS:
            costs[k] = list(rtl[k]["suggest"])
        dfa = (Path(a.rtl_model) / "boom.md").read_text()
        if a.variant == "D":
            costs["int_mul"] = list(ANISH_WINNER["costs"]["int_mul"])
        if a.variant == "E":
            divmod = "true"
    else:
        costs["int_div"] = list(rtl["int_div"]["suggest"])
        dfa = anish_dfa_gcc15(pristine["riscv.md"])
    out = render(pristine, costs, dfa, ANISH_WINNER["move_profile"], ANISH_WINNER["policy"],
                 ANISH_WINNER["issue_rate"], divmod)
    od = Path(a.out)
    for n, t in out.items():
        (od / n).write_text(t)
    rec = {"variant": a.variant, "costs": costs, "divmod_override": divmod, **{k: ANISH_WINNER[k] for k in
           ("move_profile", "policy", "issue_rate")},
           "sha256": {n: hashlib.sha256(t.encode()).hexdigest() for n, t in out.items()}}
    print(json.dumps(rec, indent=1))


if __name__ == "__main__":
    main()
