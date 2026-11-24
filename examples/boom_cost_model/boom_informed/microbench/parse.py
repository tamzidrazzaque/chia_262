#!/usr/bin/env python3
"""Turn microbench console logs into results.json / results.csv / summary.txt.

  python3 parse.py --manifest build/manifest.json --source LABEL --out DIR log...

Per kernel: min/median timed cycles over the reps, net = min - ctl_empty(min)
of the same log (rdcycle/rdinstret serialization overhead), per_op = net/ops,
and the two PREDICTIONS from the manifest (boom.md model, rtl-source estimate).
Every row carries the "source" label; spike output is functional only.
"""
import argparse
import csv
import json
import os
import re
import statistics

LINE = re.compile(r"MB k=(\S+) ops=(\d+) cyc=([\d,]+) ins=([\d,]+) sum=([0-9a-f]+) exp=([0-9a-f]+) ok=(\d)")
BEGIN = re.compile(r"MB-BEGIN group=(\S+)(?:.*marchid=(\d+))?")
END = re.compile(r"MB-END group=(\S+) pass=(\d+) fail=(\d+) total_cycles=(\d+)")


def parse_log(path):
    runs, cur = [], None
    for line in open(path, errors="replace"):
        m = BEGIN.search(line)
        if m:
            cur = {"group": m.group(1), "log": path, "kernels": {}, "end": None,
                   "marchid": int(m.group(2)) if m.group(2) else None}
            runs.append(cur)
            continue
        m = LINE.search(line)
        if m and cur is not None:
            name = m.group(1)
            cur["kernels"][name] = {
                "ops": int(m.group(2)),
                "cyc": [int(v) for v in m.group(3).split(",")],
                "ins": [int(v) for v in m.group(4).split(",")],
                "sum": m.group(5), "exp": m.group(6), "ok": m.group(7) == "1"}
            continue
        m = END.search(line)
        if m and cur is not None:
            cur["end"] = {"pass": int(m.group(2)), "fail": int(m.group(3)), "total_cycles": int(m.group(4))}
    return runs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "build", "manifest.json"))
    ap.add_argument("--source", required=True, help="e.g. verilator-megaboomv3, firesim-f2-megaboom, spike-functional-NOT-timing")
    ap.add_argument("--out", required=True)
    ap.add_argument("logs", nargs="+")
    a = ap.parse_args()
    man = {k["name"]: k for k in json.load(open(a.manifest))["kernels"]}
    os.makedirs(a.out, exist_ok=True)
    rows, problems, groups = [], [], {}
    timing = not a.source.startswith("spike")
    for path in a.logs:
        for run in parse_log(path):
            g = run["group"]
            groups[g] = {"log": path, "end": run["end"], "n": len(run["kernels"]), "marchid": run["marchid"]}
            if timing and run["marchid"] != 2:
                problems.append(f"{g}: marchid={run['marchid']} is not BOOM (2) -- wrong core/AGFI? ({path})")
            if run["end"] is None:
                problems.append(f"{g}: no MB-END line in {path} (truncated run?)")
            ks = run["kernels"]
            base = min(ks["ctl_empty"]["cyc"]) if "ctl_empty" in ks else 0
            base_i = min(ks["ctl_empty"]["ins"]) if "ctl_empty" in ks else 0
            addlat = None
            if "ctl_add_dep" in ks:
                addlat = (min(ks["ctl_add_dep"]["cyc"]) - base) / ks["ctl_add_dep"]["ops"]
            for name, r in ks.items():
                mk = man.get(name)
                if mk is None:
                    problems.append(f"{g}: kernel {name} not in manifest")
                    continue
                if mk["expect"] != r["exp"]:
                    problems.append(f"{name}: binary expect {r['exp']} != manifest {mk['expect']} (stale build?)")
                if not r["ok"]:
                    problems.append(f"{name}: CHECKSUM FAIL sum={r['sum']} exp={r['exp']}")
                cmin, cmed = min(r["cyc"]), statistics.median(r["cyc"])
                net = cmin - base if name != "ctl_empty" else cmin
                per_op = net / r["ops"]
                meta = mk["meta"]
                row = {"source": a.source, "group": g, "kernel": name, "cat": meta.get("cat"),
                       "ops": r["ops"], "ok": int(r["ok"]),
                       "cyc_min": cmin, "cyc_med": cmed, "cyc_max": max(r["cyc"]),
                       "cyc_spread": max(r["cyc"]) - cmin, "ctl_empty_cyc": base,
                       "net_cyc": net, "per_op": round(per_op, 3),
                       "ins_min": min(r["ins"]), "net_ins": min(r["ins"]) - base_i,
                       "dyn_insts_expected": mk["dyn_insts"],
                       "pred_boommd_per_op": mk["pred"]["boommd"]["per_op"],
                       "pred_rtlsrc_per_op": mk["pred"]["rtlsrc"]["per_op"],
                       "rtlsrc_div_core_mean": mk["pred"]["rtlsrc"].get("div_core_cycles_mean", ""),
                       "meas_over_boommd": round(per_op / mk["pred"]["boommd"]["per_op"], 3) if timing and mk["pred"]["boommd"]["per_op"] else "",
                       "meas_over_rtlsrc": round(per_op / mk["pred"]["rtlsrc"]["per_op"], 3) if timing and mk["pred"]["rtlsrc"]["per_op"] else "",
                       "add_lat_ctl": round(addlat, 3) if addlat is not None else ""}
                # op-latency estimate for single-chain kernels with an 'add M' fixup
                if meta.get("chains") == 1 and meta.get("fixup") and addlat is not None:
                    row["op_lat_est"] = round(per_op - addlat, 3)
                else:
                    row["op_lat_est"] = ""
                for key in ("op", "cls", "variant", "chains", "fn", "c", "impl", "width", "signed", "K", "T", "d"):
                    row["m_" + key] = meta.get(key, "")
                rows.append(row)
    fields = list(rows[0].keys()) if rows else []
    with open(os.path.join(a.out, "results.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    json.dump({"source": a.source, "timing_valid": timing, "groups": groups,
               "problems": problems, "rows": rows}, open(os.path.join(a.out, "results.json"), "w"), indent=1)

    S = [f"source={a.source} timing_valid={timing} kernels={len(rows)} "
         f"checksum_fail={sum(1 for r in rows if not r['ok'])}"]
    if not timing:
        S.append("NOTE: spike cycle counts are NOT timing; only checksums/instret are meaningful.")
    # every group has its own ctl_empty row (the baseline itself), so exclude all of them
    inst_rows = [r for r in rows if r["kernel"] != "ctl_empty"]
    inst_bad = [r["kernel"] for r in inst_rows if r["net_ins"] != r["dyn_insts_expected"]]
    S.append(f"instret(net) == interpreter dynamic insts for {len(inst_rows) - len(inst_bad)}/{len(inst_rows)} "
             f"non-empty kernel instances; mismatches: {inst_bad[:10]}")
    for g, v in groups.items():
        S.append(f"group {g}: {v['n']} kernels end={v['end']}")
    S += ["problems:"] + [f"  {p}" for p in problems]
    if timing:
        by = {r["kernel"]: r for r in rows}
        S.append("\nunit kernels: per_op cycles (measured | boom.md | rtl-src)")
        for r in rows:
            if r["cat"] == "unit":
                S.append(f"  {r['kernel']:22s} {r['per_op']:8.2f} | {r['pred_boommd_per_op']:7.2f} | {r['pred_rtlsrc_per_op']:7.2f}"
                         + (f"   op_lat_est={r['op_lat_est']}" if r["op_lat_est"] != "" else ""))
        S.append("\ndiv-by-constant: hw cycles/op vs GCC sequence cycles/op (speedup = hw/seq)")
        for r in rows:
            if r["cat"] == "divconst" and r["m_impl"] == "hw":
                s = by.get(r["kernel"].replace("_hw_", "_seq_"))
                if s:
                    S.append(f"  {r['m_fn']:10s} {r['m_variant']}  hw={r['per_op']:7.2f}  seq={s['per_op']:6.2f}  "
                             f"speedup={r['per_op'] / max(s['per_op'], 1e-9):5.2f}")
        S.append("\nhide (cycles per block of 1 div + K addi):")
        for r in rows:
            if r["cat"] == "hide":
                S.append(f"  {r['kernel']:22s} {r['per_op']:7.2f}  (boom.md {r['pred_boommd_per_op']}, rtl {r['pred_rtlsrc_per_op']})")
        S.append("\ninvariant divisor loops (cycles per iteration; lemire includes the 1 precompute divu):")
        for r in rows:
            if r["cat"] == "invariant":
                S.append(f"  {r['kernel']:24s} {r['per_op']:7.2f}  (boom.md {r['pred_boommd_per_op']}, rtl {r['pred_rtlsrc_per_op']})")
        S.append("\nshare:")
        for r in rows:
            if r["cat"] == "share":
                S.append(f"  {r['kernel']:22s} {r['per_op']:7.2f}")
    open(os.path.join(a.out, "summary.txt"), "w").write("\n".join(S) + "\n")
    print("\n".join(S[:8 + len(groups) + len(problems)]))
    print(f"wrote {a.out}/results.csv results.json summary.txt")


if __name__ == "__main__":
    main()
