#!/usr/bin/env python3
"""Join [verilator-megaboom-rtl] measurements (all code layouts L0..L3) with
[model] predictions.  Per (kernel, variant): last-rep cycles for each layout,
mean/min/max over layouts; speedup = mean(ooo) / mean(variant).
Writes results/summary.csv and results/summary_layouts.csv; prints a table."""
import re, json, glob, os, csv, statistics as st
H = os.path.dirname(os.path.abspath(__file__))
VORDER = ["ooo", "rocket", "inv", "occ66", "occ1"]
meas = {}   # (k, v) -> {layout: cyc}
bad = []
for f in sorted(glob.glob(f"{H}/results/verilator-megaboom-rtl/rk_*.log")):
    b = os.path.basename(f)[3:-4]
    g, _, L = b.partition("_L")
    L = "L" + (L or "0")
    for line in open(f, errors="replace"):
        m = re.match(r"RK k=(\S+) v=(\S+) cyc=(\S+) ins=(\S+) sum=(\S+) exp=(\S+) ok=(\d)", line)
        if m:
            cyc = [int(x) for x in m.group(3).split(",")]
            if m.group(7) != "1": bad.append((b, m.group(1), m.group(2)))
            meas.setdefault((m.group(1), m.group(2)), {})[L] = cyc[-1]
model = {}
for f in glob.glob(f"{H}/results/model/*.json"):
    for r in json.load(open(f)):
        model[(r["k"], r["v"])] = r
keys = sorted(set(meas) | set(model), key=lambda kv: (kv[0], VORDER.index(kv[1]) if kv[1] in VORDER else 9))
rows, lrows = [], []
for k, v in keys:
    M = meas.get((k, v), {}); R = model.get((k, v)); B = meas.get((k, "ooo"), {}); RB = model.get((k, "ooo"))
    row = dict(kernel=k, variant=v, layouts=len(M))
    if M:
        vals = list(M.values())
        row.update(meas_mean=round(st.mean(vals)), meas_min=min(vals), meas_max=max(vals),
                   meas_spread_pct=round(100 * (max(vals) - min(vals)) / st.mean(vals), 1))
        if B:
            row["meas_speedup"] = round(st.mean(B.values()) / st.mean(vals), 3)
            common = [L for L in M if L in B]
            if common:
                sp = [B[L] / M[L] for L in common]
                row["speedup_min"] = round(min(sp), 3); row["speedup_max"] = round(max(sp), 3)
        for L, c in sorted(M.items()):
            lrows.append(dict(kernel=k, variant=v, layout=L, cycles=c))
    if R:
        row.update(model_rtl=R["cyc_rtl"], model_rtl_bp=R["cyc_rtl_bp"], model_boommd=R["cyc_boommd"],
                   ndiv=R["ndiv"], divlat_rtl_avg=R["div_lat_rtl_avg"], spike_ins=R["insts"], mispred_gshare=R.get("mispred_gshare"))
        if RB:
            row["rtl_speedup"] = round(RB["cyc_rtl"] / R["cyc_rtl"], 3)
            row["rtl_bp_speedup"] = round(RB["cyc_rtl_bp"] / R["cyc_rtl_bp"], 3)
            row["boommd_speedup"] = round(RB["cyc_boommd"] / R["cyc_boommd"], 3)
    if M and R:
        row["rtl_bp_err_pct"] = round(100 * (R["cyc_rtl_bp"] - row["meas_mean"]) / row["meas_mean"], 1)
    rows.append(row)
cols = ["kernel", "variant", "layouts", "meas_mean", "meas_min", "meas_max", "meas_spread_pct", "meas_speedup", "speedup_min", "speedup_max",
        "rtl_speedup", "rtl_bp_speedup", "boommd_speedup", "model_rtl", "model_rtl_bp", "model_boommd", "rtl_bp_err_pct",
        "spike_ins", "ndiv", "divlat_rtl_avg", "mispred_gshare"]
with open(f"{H}/results/summary.csv", "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=cols); w.writeheader()
    for r in rows: w.writerow({c: r.get(c, "") for c in cols})
with open(f"{H}/results/summary_layouts.csv", "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=["kernel", "variant", "layout", "cycles"]); w.writeheader()
    for r in lrows: w.writerow(r)
show = ["kernel", "variant", "layouts", "meas_mean", "meas_spread_pct", "meas_speedup", "speedup_min", "speedup_max",
        "rtl_speedup", "rtl_bp_speedup", "boommd_speedup", "rtl_bp_err_pct"]
print(" ".join(f"{c[:11]:>11s}" for c in show))
for r in rows:
    print(" ".join(f"{str(r.get(c, ''))[:18] if i == 0 else str(r.get(c, '')):>11s}" if i else f"{r[c]:<18s}" for i, c in enumerate(show)))
if bad: print("CHECKSUM FAILURES:", bad)
