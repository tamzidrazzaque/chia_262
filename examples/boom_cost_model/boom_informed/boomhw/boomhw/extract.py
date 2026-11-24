"""Extract compiler-relevant MegaBOOM V3 microarchitecture facts from the
BOOM / rocket-chip / chipyard Scala sources, with file:line provenance.

Facts come in three kinds, recorded in each entry's 'kind':
  'param'   - a generator parameter value read from a config / default
  'struct'  - a structural fact read from generator code (port assignment,
              decode-table FU class, which FU implements an op)
  'derived' - a timing consequence computed from params + code anchors; every
              anchor's file:line is listed so the reasoning can be audited
"""
import json
import re

from .scala_src import Prov, SourceTree, SourceError
from . import muldiv_model as mdm

P = {
    "cy_boom": "chipyard/src/main/scala/config/BoomConfigs.scala",
    "mixins": "boom/src/main/scala/v3/common/config-mixins.scala",
    "params": "boom/src/main/scala/v3/common/parameters.scala",
    "exus": "boom/src/main/scala/v3/exu/execution-units/execution-units.scala",
    "exu": "boom/src/main/scala/v3/exu/execution-units/execution-unit.scala",
    "fu": "boom/src/main/scala/v3/exu/execution-units/functional-unit.scala",
    "fpu": "boom/src/main/scala/v3/exu/execution-units/fpu.scala",
    "fdiv": "boom/src/main/scala/v3/exu/execution-units/fdiv.scala",
    "core": "boom/src/main/scala/v3/exu/core.scala",
    "decode": "boom/src/main/scala/v3/exu/decode.scala",
    "rr": "boom/src/main/scala/v3/exu/register-read/register-read.scala",
    "islot": "boom/src/main/scala/v3/exu/issue-units/issue-slot.scala",
    "fpp": "boom/src/main/scala/v3/exu/fp-pipeline.scala",
    "lsu": "boom/src/main/scala/v3/lsu/lsu.scala",
    "frontend": "boom/src/main/scala/v3/ifu/frontend.scala",
    "mul": "rocket-chip/src/main/scala/rocket/Multiplier.scala",
    "rfpu": "rocket-chip/src/main/scala/tile/FPU.scala",
    "hc": "rocket-chip/src/main/scala/rocket/HellaCache.scala",
    "ic": "rocket-chip/src/main/scala/rocket/ICache.scala",
    "alu": "rocket-chip/src/main/scala/rocket/ALU.scala",
    "hf_ds": "hardfloat/hardfloat/src/main/scala/DivSqrtRecF64_mulAddZ31.scala",
}

CONFIG = "MegaBoomV3Config"
INT_FU_FLAGS = ["hasJmpUnit", "hasCSR", "hasRocc", "hasMul", "hasDiv", "hasIfpu"]


def fact(value, src, kind, note=None, **extra):
    d = {"value": value, "src": src if isinstance(src, list) else [src], "kind": kind}
    if note:
        d["note"] = note
    d.update(extra)
    return d


# --------------------------------------------------------------------------
def config_chain(st, config=CONFIG):
    o, c = st.block(P["cy_boom"], r"class " + config + r" extends Config\s*\(")
    t = st.text(P["cy_boom"])
    body = t[o:c]
    frags = [(m.group(1), st.where(P["cy_boom"], o + m.start()))
             for m in re.finditer(r"new\s+([\w\.]+(?:\([^)]*\))?)", body)]
    return {"config": config, "src": st.where(P["cy_boom"], o), "fragments":
            [{"fragment": f, "src": s} for f, s in frags]}


def mega_core_params(st):
    """BoomCoreParams effective values = case-class defaults overlaid by WithNMegaBooms."""
    defaults = st.case_class_defaults(P["params"], "BoomCoreParams")
    lo, hi = st.block(P["mixins"], r"class WithNMegaBooms\(n: Int = 1\) extends Config\s*\(")
    core_call = st.find_call_in(P["mixins"], "BoomCoreParams", lo, hi)
    overrides = st.named_call_args(P["mixins"], *core_call)
    eff = {}
    for k, prov in defaults.items():
        eff[k] = overrides.get(k, prov)
    for k, prov in overrides.items():
        eff.setdefault(k, prov)
    # TAGE-L mixin applied by WithNMegaBooms
    tlo, thi = st.block(P["mixins"], r"class WithTAGELBPD extends Config\s*\(")
    copy_call = st.find_call_in(P["mixins"], "copy", tlo, thi)
    copy_call = st.find_call_in(P["mixins"], "copy", copy_call[0] + 1, thi)  # core.copy(...)
    copy_call = st.find_call_in(P["mixins"], "copy", copy_call[0] + 1, thi)
    for k, prov in st.named_call_args(P["mixins"], *copy_call).items():
        if k in ("bpdMaxMetaLength", "globalHistoryLength", "localHistoryLength", "localHistoryNSets"):
            prov["origin"] = "config(WithTAGELBPD)"
            eff[k] = prov
    mega_has_tage, src = st.anchor(P["mixins"], r"class WithNMegaBooms[^\n]*\n\s*new WithTAGELBPD")
    # issue params
    iqs = []
    for o, c in st.find_calls_in(P["mixins"], "IssueParams", core_call[0], core_call[1]):
        a = st.named_call_args(P["mixins"], o, c)
        iqs.append({k: v for k, v in a.items()} | {"src": st.where(P["mixins"], o)})
    # nested param objects
    nested = {}
    for name in ("DCacheParams", "ICacheParams", "FtqParameters"):
        call = st.find_call_in(P["mixins"], name, lo, hi)
        nested[name] = (st.named_call_args(P["mixins"], *call), st.where(P["mixins"], call[0]))
    fpu_call = st.find_call_in(P["mixins"], "FPUParams", core_call[0], core_call[1])
    nested["FPUParams"] = (st.named_call_args(P["mixins"], *fpu_call), st.where(P["mixins"], fpu_call[0]))
    return eff, iqs, nested, {"tage_mixin_src": src}


def overlay(st, path, cls, overrides):
    d = st.case_class_defaults(path, cls)
    out = {}
    for k, prov in d.items():
        out[k] = overrides.get(k, prov)
    return out


def int_port_map(st, int_width, use_fpu=True, use_rocc=False):
    """Replicate execution-units.scala is_nth() port assignment, reading the
    n for each FU flag from the source."""
    t = st.text(P["exus"])
    m, src_loop = st.anchor(P["exus"], r"for \(w <- 0 until int_width\) \{")
    _, src_nth = st.anchor(P["exus"], r"def is_nth\(n: Int\): Boolean = w == \(\(n\) % int_width\)")
    blk_o, blk_c = st.block(P["exus"], r"val alu_exe_unit = Module\(new ALUExeUnit")
    flags = {}
    for arg, off in st.split_args(P["exus"], blk_o, blk_c):
        mm = re.match(r"(\w+)\s*=\s*is_nth\((\d+)\)(.*)", arg)
        if mm:
            flags[mm.group(1)] = (int(mm.group(2)), mm.group(3).strip(), st.where(P["exus"], off))
    ports = []
    for w in range(int_width):
        fus = ["ALU"]  # ALUExeUnit hasAlu defaults to true
        srcs = []
        for flag, (n, cond, src) in flags.items():
            on = (w == n % int_width)
            if "usingRoCC" in cond:
                on = on and use_rocc
            if "usingFPU" in cond:
                on = on and use_fpu
            if on:
                fus.append({"hasJmpUnit": "JMP", "hasCSR": "CSR", "hasRocc": "ROCC",
                            "hasMul": "IMUL", "hasDiv": "IDIV", "hasIfpu": "I2F"}[flag])
                srcs.append(src)
        ports.append({"port": f"int{w}", "fus": fus, "src": [src_loop, src_nth] + srcs})
    return ports, flags


def fp_port_map(st, fp_width, use_fdiv=True):
    _, src = st.anchor(P["exus"], r"hasFdiv = usingFDivSqrt && \(w==0\)")
    _, src2 = st.anchor(P["exus"], r"hasFpiu = \(w==0\)")
    ports = []
    for w in range(fp_width):
        fus = ["FPU(FMA/FADD/FMUL/FMV/FCVT-FF)"]
        if w == 0 and use_fdiv:
            fus.append("FDIV/FSQRT")
        if w == 0:
            fus.append("F2I(FPIU: fmv.x, fcvt.x.f, fcmp, fclass, fp-store data)")
        ports.append({"port": f"fp{w}", "fus": fus, "src": [src, src2]})
    return ports


DECODE_ROW = re.compile(
    r"^\s*(\w+)\s*->\s*List\(([^\n]*)\)", re.M)


def decode_table(st):
    """Parse BOOM decode rows: insn -> uopc, iq, fu, wakeup_delay, bypassable, is_br."""
    rows = {}
    t = st.text(P["decode"])
    for m in DECODE_ROW.finditer(t):
        fields = [f.strip() for f in m.group(2).split(",")]
        if len(fields) < 20 or not fields[3].startswith("uop"):
            continue
        name = m.group(1)
        rows.setdefault(name, {
            "uopc": fields[3], "iq": fields[4], "fu": fields[5],
            "wakeup_delay": fields[17], "bypassable": fields[18] == "Y",
            "is_br": fields[19] == "Y", "src": st.where(P["decode"], m.start(1))})
    if "DIVW" not in rows or "MULHU" not in rows:
        raise SourceError("decode table parse failed")
    return rows


# --------------------------------------------------------------------------
def pipeline_anchors(st):
    """Code anchors behind the timing derivation."""
    A = {}

    def a(key, path, pat, note):
        _, src = st.anchor(P[path], pat)
        A[key] = {"src": src, "note": note}

    a("rrd_regnext", "rr", r"rrd_valids\(w\) := RegNext\(",
      "issue -> register-read is a register stage (I+1)")
    a("exe_reg", "rr", r"exe_reg_valids\(w\) := Mux\(rrd_kill",
      "register-read -> execute is a register stage (EX = I+2)")
    a("fast_wakeup", "core", r"fast_wakeup\.valid\s*:= iss_valids\(i\) &&\s*\n\s*iss_uops\(i\)\.bypassable",
      "bypassable (ALU) uops wake dependents in their own issue cycle")
    a("slow_wakeup", "core", r"slow_wakeup\.valid\s*:= resp\.valid &&",
      "non-bypassable uops wake dependents when their result is on the writeback port")
    a("slot_wakeup_reg", "islot", r"when \(io\.wakeup_ports\(i\)\.valid &&",
      "issue-slot ready bits are registers: a wakeup in cycle t allows issue in t+1")
    a("pfu_resp", "fu", r"io\.resp\.valid\s*:= r_valids\(numStages-1\)",
      "pipelined FU result valid numStages cycles after EX")
    a("imul_unit", "exu", r"imul = Module\(new PipelinedMulUnit\(imulLatency, xLen\)\)",
      "integer multiply (incl. mulh/mulhu/mulhsu/mulw) uses the pipelined multiplier")
    a("div_unit", "fu", r"val div = Module\(new freechips\.rocketchip\.rocket\.MulDiv\(mulDivParams, width = dataWidth\)\)",
      "integer divide/remainder uses the iterative rocket MulDiv (64-bit datapath also for W ops)")
    a("div_no_mul", "fu", r"We don't use the iterative multiply functionality here",
      "MulDiv multiply path unused in BOOM")
    a("div_busy", "exu", r"div_busy\s*:= !div\.io\.req\.ready \|\|",
      "FU_DIV is withheld from the issue port while MulDiv is busy; ALU on that port is not")
    a("div_fu_types", "exu", r"Mux\(!div_busy && hasDiv\.B, FU_DIV, 0\.U\)",
      "only the DIV capability bit is masked")
    a("div_issue_mask", "core", r"fu_types = fu_types & RegNext\(~Mux\(idiv_issued, FU_DIV, 0\.U\)\)",
      "a just-issued div blocks div issue for the next cycle (it reaches EX 2 cycles later)")
    a("div_wb_share", "exu", r"div\.io\.resp\.ready := !\(iresp_fu_units\.map\(_\.io\.resp\.valid\)\.reduce\(_\|_\)\)",
      "div result waits if the port's ALU writes back that cycle")
    a("alu_mul_stages", "exu", r"if \(hasAlu && hasMul\) 3",
      "ALU on the multiplier port is padded to 3 stages (bypassed) so ALU/MUL never collide on writeback")
    a("spec_ld_wakeup", "lsu", r"io\.core\.spec_ld_wakeup\(w\)\.valid := enableFastLoadUse\.B",
      "integer loads speculatively wake dependents from DCache stage s1")
    a("mem_incoming", "lsu", r"val mem_incoming_uop\s*= RegNext\(",
      "s1 is one cycle after the address/EX cycle")
    a("spec_ld_not_fp", "lsu", r"!mem_incoming_uop\(w\)\.fp_val",
      "FP loads do not use speculative wakeup")
    a("maddr_comb", "fu", r"class MemAddrCalcUnit\(implicit p: Parameters\)\s*\n\s*extends PipelinedFunctionalUnit\(\s*\n\s*numStages = 0",
      "address generation is combinational in EX; DCache s0 = EX")
    a("fpu_pad", "fpu", r"val fpu_latency = dfmaLatency",
      "all FPU ops (fma, fpmu, fpiu) padded to dfmaLatency")
    a("fpu_unit_stages", "fu", r"numStages = p\(tile\.TileKey\)\.core\.fpu\.get\.dfmaLatency",
      "FPUUnit result valid dfmaLatency cycles after EX")
    a("fp_wakeup", "fpp", r"issue_wakeup\.valid := writeback\.valid",
      "FP wakeups come from writeback (no FP bypass)")
    a("fdiv_one", "fdiv", r"io\.req\.ready := !r_buffer_val",
      "FDivSqrt: one-entry input buffer, one op in the hardfloat unit at a time")
    a("fdiv_hw", "fdiv", r"val divsqrt = Module\(new hardfloat\.DivSqrtRecF64\)",
      "FP div/sqrt = hardfloat DivSqrtRecF64 (single precision is up-converted to double)")
    a("ifpu", "exu", r"ifpu = Module\(new IntToFPUnit\(latency=intToFpLatency\)\)",
      "int->FP conversion/moves run on an integer issue port")
    a("ld_misalign", "lsu", r"Mux\(ma_ld\(w\), rocket\.Causes\.misaligned_load\.U",
      "misaligned loads raise an exception (software emulation)")
    a("no_zb", "params", r"val useZba = false",
      "no Zba/Zbb/Zbs/Zicond in BOOM v3")
    a("br_b2", "core", r"val b2    = Reg\(new BrResolutionInfo\)",
      "branch resolution registered one cycle after EX before redirect")
    return A


# --------------------------------------------------------------------------
def extract(src_root, elaborated_log=None, dts=None):
    st = SourceTree(src_root)
    model = {"schema": "boom-hw-model/1", "target": CONFIG}
    model["config_chain"] = config_chain(st)
    core, iqs, nested, tage = mega_core_params(st)

    def cp(name):
        p = core[name]
        return fact(p["value"], p["src"], "param", origin=p["origin"], expr=p.get("expr"))

    keys = ["fetchWidth", "decodeWidth", "numRobEntries", "numIntPhysRegisters",
            "numFpPhysRegisters", "numLdqEntries", "numStqEntries", "maxBrCount",
            "numFetchBufferEntries", "enablePrefetching", "enableFastLoadUse",
            "enableAgePriorityIssue", "imulLatency", "intToFpLatency", "numRasEntries",
            "globalHistoryLength", "useCompressed", "numDCacheBanks", "enableSFBOpt",
            "nL2TLBEntries", "useAtomics", "useVM"]
    model["core"] = {k: cp(k) for k in keys}
    model["core"]["branchPredictor"] = fact("TAGE-L (loop, TAGE, BTB, uBTB, BIM)", tage["tage_mixin_src"], "param")
    _, retire_src = st.anchor(P["params"], r"val retireWidth = decodeWidth")
    model["core"]["retireWidth"] = fact(model["core"]["decodeWidth"]["value"], [retire_src], "struct")
    for zb in ("useZba", "useZbb", "useZbs", "useConditionalZero"):
        m, s = st.anchor(P["params"], r"val " + zb + r" = (true|false)")
        model["core"][zb] = fact(m.group(1) == "true", s, "param")

    # FTQ
    ftq_args, ftq_src = nested["FtqParameters"]
    model["core"]["ftqEntries"] = fact(ftq_args["nEntries"]["value"], ftq_args["nEntries"]["src"], "param")

    # issue queues
    model["issue_queues"] = {}
    for q in iqs:
        typ = q["iqType"]["value"].replace("IQT_", "").lower()
        model["issue_queues"][typ] = {k: fact(q[k]["value"], q[k]["src"], "param")
                                      for k in ("issueWidth", "numEntries", "dispatchWidth")}
    int_w = model["issue_queues"]["int"]["issueWidth"]["value"]
    mem_w = model["issue_queues"]["mem"]["issueWidth"]["value"]
    fp_w = model["issue_queues"]["fp"]["issueWidth"]["value"]

    # FPU params
    fpu_over, fpu_src = nested["FPUParams"]
    fpu = overlay(st, P["rfpu"], "FPUParams", fpu_over)
    model["fpu_params"] = {k: fact(v["value"], v["src"], "param", origin=v["origin"]) for k, v in fpu.items()}

    # MulDiv params
    md_default = core["mulDiv"]
    mm = re.fullmatch(r"Some\(MulDivParams\((.*)\)\)", md_default["expr"])
    md_over = {}
    if mm:
        for kv in mm.group(1).split(","):
            if "=" in kv:
                k, v = [x.strip() for x in kv.split("=")]
                md_over[k] = Prov(value=literal_bool(v), src=md_default["src"],
                                  origin=md_default["origin"], expr=v)
    md = overlay(st, P["mul"], "MulDivParams", md_over)
    _, mdp_src = st.anchor(P["params"], r"val mulDivParams = boomParams\.mulDiv\.getOrElse")
    model["muldiv_params"] = {k: fact(v["value"], [v["src"], mdp_src], "param", origin=v["origin"])
                              for k, v in md.items()}

    # caches
    dc_over, dc_src = nested["DCacheParams"]
    ic_over, ic_src = nested["ICacheParams"]
    dc = overlay(st, P["hc"], "DCacheParams", dc_over)
    ic = overlay(st, P["ic"], "ICacheParams", ic_over)
    model["caches"] = {
        "dcache": {k: fact(dc[k]["value"], dc[k]["src"], "param", origin=dc[k]["origin"])
                   for k in ("nSets", "nWays", "rowBits", "nMSHRs", "nTLBWays", "blockBytes")},
        "icache": {k: fact(ic[k]["value"], ic[k]["src"], "param", origin=ic[k]["origin"])
                   for k in ("nSets", "nWays", "rowBits", "fetchBytes", "nTLBWays", "blockBytes", "latency")},
    }
    for c in ("dcache", "icache"):
        cc = model["caches"][c]
        size = cc["nSets"]["value"] * cc["nWays"]["value"] * cc["blockBytes"]["value"]
        cc["sizeBytes"] = fact(size, cc["nSets"]["src"] + cc["nWays"]["src"] + cc["blockBytes"]["src"],
                               "derived", note="nSets*nWays*blockBytes")

    # execution ports
    int_ports, flags = int_port_map(st, int_w)
    _, mem_src = st.anchor(P["exus"], r"for \(w <- 0 until memWidth\)")
    mem_ports = [{"port": f"mem{w}", "fus": ["AGU/LSU (load, store-addr+int-store-data)"], "src": [mem_src]}
                 for w in range(mem_w)]
    fp_ports = fp_port_map(st, fp_w, use_fdiv=fpu["divSqrt"]["value"])
    model["exec_ports"] = {"int": int_ports, "mem": mem_ports, "fp": fp_ports}
    model["decode"] = decode_table(st)
    model["anchors"] = pipeline_anchors(st)

    # hardfloat div/sqrt core cycle structure (A/B/C/E phase counters)
    hf = {}
    for key, pat in [("A_div", r"Mux\(entering_PA_normalCase_div,\s*(\d+)\.U"),
                     ("A_sqrt", r"Mux\(entering_PA_normalCase_sqrt,\s*(\d+)\.U"),
                     ("B", r"Mux\(sqrtOp_PA, (\d+)\.U, (\d+)\.U\)"),
                     ("C", r"Mux\(cyc_B1, Mux\(sqrtOp_PB, (\d+)\.U, (\d+)\.U\)"),
                     ("E", r"cycleNum_E := Mux\(cyc_C1, (\d+)\.U")]:
        m, s = st.anchor(P["hf_ds"], pat)
        hf[key] = {"groups": [int(g) for g in m.groups()], "src": s}
    model["hardfloat_divsqrt_phases"] = hf

    if elaborated_log:
        model["elaboration_crosscheck"] = crosscheck_log(model, elaborated_log)
    if dts:
        model["dts"] = parse_dts(dts)
    return model


def literal_bool(v):
    return {"true": True, "false": False}.get(v, int(v) if v.isdigit() else v)


# --------------------------------------------------------------------------
def crosscheck_log(model, path):
    """Compare source-derived values with BOOM's own elaboration printout."""
    txt = open(path, encoding="utf-8", errors="replace").read()
    checks = []

    def chk(name, pat, expect, conv=int):
        m = re.search(pat, txt)
        got = conv(m.group(1)) if m else None
        checks.append({"item": name, "source_model": expect, "elaborated": got, "match": got == expect})

    c = model["core"]
    chk("fetchWidth", r"Fetch Width\s*:\s*(\d+)", c["fetchWidth"]["value"])
    chk("decodeWidth", r"Decode Width\s*:\s*(\d+)", c["decodeWidth"]["value"])
    chk("numRobEntries", r"ROB Size\s*:\s*(\d+)", c["numRobEntries"]["value"])
    chk("numIntPhysRegisters", r"Num Int Phys Registers:\s*(\d+)", c["numIntPhysRegisters"]["value"])
    chk("numFpPhysRegisters", r"Num FP  Phys Registers:\s*(\d+)", c["numFpPhysRegisters"]["value"])
    chk("maxBrCount", r"Max Branch Count\s*:\s*(\d+)", c["maxBrCount"]["value"])
    chk("LDQ/STQ", r"Load/Store Unit Size\s*:\s*(\d+/\d+)",
        f"{c['numLdqEntries']['value']}/{c['numStqEntries']['value']}", conv=str)
    iq = model["issue_queues"]
    chk("issue window sizes", r"Issue Window Size\s*:\s*List\(([\d, ]+)\)",
        f"{iq['mem']['numEntries']['value']}, {iq['int']['numEntries']['value']}, {iq['fp']['numEntries']['value']}", conv=str)
    total_issue = sum(q["issueWidth"]["value"] for q in iq.values())
    chk("total issue width", r"Issue Width\s*:\s*(\d+)", total_issue)
    dc = model["caches"]["dcache"]
    chk("DCache sets", r"DCache Sets\s*:\s*(\d+)", dc["nSets"]["value"])
    chk("DCache ways", r"DCache Ways\s*:\s*(\d+)", dc["nWays"]["value"])
    chk("DCache MSHRs", r"DCache nMSHRs\s*:\s*(\d+)", dc["nMSHRs"]["value"])
    # exe unit list as printed by BOOM
    units = re.findall(r"==ExeUnit==\n((?:\[C0\]\s+- [^\n]+\n)*)", txt)
    printed = [[l.split("- ", 1)[1].strip() for l in u.strip().splitlines()] for u in units]
    ours = [["Mem"]] * len(model["exec_ports"]["mem"]) + [
        [{"ALU": "ALU", "IMUL": "Mul", "IDIV": "Div", "I2F": "IFPU"}[f] for f in p["fus"]
         if f in ("ALU", "IMUL", "IDIV", "I2F")] for p in model["exec_ports"]["int"]]
    checks.append({"item": "integer exe units (BOOM printout order)", "source_model": ours,
                   "elaborated": printed[:len(ours)], "match": printed[:len(ours)] == ours})
    return {"log": path, "checks": checks, "all_match": all(c["match"] for c in checks)}


def parse_dts(path):
    t = open(path, encoding="utf-8").read()
    g = lambda pat: (re.search(pat, t).group(1) if re.search(pat, t) else None)
    return {"src": path, "isa": g(r'riscv,isa = "([^"]+)"'),
            "d_cache_size": int(g(r"d-cache-size = <(\d+)>")),
            "i_cache_size": int(g(r"i-cache-size = <(\d+)>")),
            "mmu": g(r'mmu-type = "([^"]+)"'),
            "l2_cache_size": int(g(r"(?<![di]-)cache-size = <(\d+)>") or 0),
            "l2_cache_sets": int(g(r"(?<![di]-)cache-sets = <(\d+)>") or 0),
            "timebase_hz": int(g(r"timebase-frequency = <(\d+)>") or 0)}


if __name__ == "__main__":
    import sys
    print(json.dumps(extract(sys.argv[1]), indent=1, default=str)[:4000])
