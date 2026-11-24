#!/usr/bin/env python3
"""Analyze range-aware-div Verilator logs.

  python3 analyze.py --manifest build/manifest.json --out results/verilator-megaboom-rtl results/.../*.log

Every measured number is labelled [verilator-megaboom-rtl] (cycle-exact MegaBoomV3Config
core RTL, SimDRAM memory); every predicted number is [model] (unit-RTL-validated MulDiv
closed form + assumed core offsets, or a dataflow latency of the GCC sequence).

Per kernel: net = min(timed cycles) - min(ctl_empty cycles).
  dep kernels : per_link = net / n   (one OP + one 1-cycle add per link; last link has no add)
                op_lat   = (net - (n-1) * add_lat) / n,  add_lat from ctl_link (should be 1)
  ind kernels : per_op = (net - ctl_ind_net) / n   (extra cycles per op over the load+add skeleton)
"""
import argparse
import csv
import json
import os
import re
import statistics
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
LINE = re.compile(r"MB k=(\S+) ops=(\d+) cyc=([\d,]+) ins=([\d,]+) sum=([0-9a-f]+) exp=([0-9a-f]+) ok=(\d)")
BEGIN = re.compile(r"MB-BEGIN group=(\S+).*marchid=(\d+)")
END = re.compile(r"MB-END group=(\S+) pass=(\d+) fail=(\d+) total_cycles=(\d+)")
MULS = {"mul", "mulw", "mulh", "mulhu"}
CORE = 3   # [model] core issue->dependent-issue cycles added to unit L (rtl-model; re-fit below)
FOFF = 6   # fixed dep-kernel offset (fit on rdsmoke: hw and seq kernels all give 6 with CORE=3)


_SEQS = None


def seq_model(t, op, d, mul_lat=6, alu_lat=1):
    """[model] dataflow latency (x -> result) and uop count of the GCC 15.1 body."""
    global _SEQS
    if _SEQS is None:
        sys.path.insert(0, HERE)
        import gen_rd
        _SEQS = gen_rd.load_seqs(os.path.join(HERE, "gccref", "rdc.rocket.s"))
    body = _SEQS[(t, op, int(d))]
    ready = {"x": 0}
    for o, dst, srcs, imm in body:
        r = 0
        for s_ in srcs:
            if s_[0] == "x":
                r = max(r, ready["x"])
            elif s_[0] == "t":
                r = max(r, ready[("t", s_[1])])
        key = "x" if dst == "x" else ("t", dst[1])
        ready[key] = r + (mul_lat if o in MULS else alu_lat)
    return ready["x"], len(body)


def parse(paths):
    K, meta = {}, {}
    for p in paths:
        g = None
        for line in open(p, errors="replace"):
            m = BEGIN.search(line)
            if m:
                g = m.group(1)
                meta[g] = {"marchid": int(m.group(2)), "log": p}
            m = LINE.search(line)
            if m and g:
                K[m.group(1)] = {"group": g, "ops": int(m.group(2)), "cyc": list(map(int, m.group(3).split(","))),
                                 "ok": m.group(7) == "1", "sum": m.group(5), "exp": m.group(6)}
                K[m.group(1) + "@" + g] = K[m.group(1)]
            m = END.search(line)
            if m and g:
                meta[g]["end"] = {"pass": int(m.group(2)), "fail": int(m.group(3)), "total": int(m.group(4))}
    return K, meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", action="append", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("logs", nargs="+")
    a = ap.parse_args()
    man = {}
    for mf in a.manifest:
        for k in json.load(open(mf))["kernels"]:
            man[(k["name"], k["group"])] = k
    K, meta = parse(a.logs)
    problems = []
    for g, m in meta.items():
        if m["marchid"] != 2:
            problems.append(f"{g}: marchid {m['marchid']} != 2 (not BOOM)")
        if "end" not in m:
            problems.append(f"{g}: truncated log (no MB-END)")
        elif m["end"]["fail"]:
            problems.append(f"{g}: {m['end']['fail']} checksum failures")
    rows = []
    groups = sorted(meta)
    base = {}
    for g in groups:
        e = K.get("ctl_empty@" + g)
        base[g] = min(e["cyc"]) if e else 0
    ctl = {}
    for g in groups:
        for nm in list(K):
            if nm.endswith("@" + g) and nm.startswith("ctl_"):
                ctl[(nm.split("@")[0], g)] = min(K[nm]["cyc"]) - base[g]
    for nm, r in K.items():
        if "@" not in nm:
            continue
        name, g = nm.split("@")
        mk = man.get((name, g))
        if mk is None:
            problems.append(f"{name}@{g} not in manifest")
            continue
        if mk["expect"] != r["exp"]:
            problems.append(f"{name}@{g}: expect mismatch (stale manifest?)")
        if not r["ok"]:
            problems.append(f"{name}@{g}: CHECKSUM FAIL")
        if len(set(r["cyc"])) != 1:
            problems.append(f"{name}@{g}: reps differ {r['cyc']}")
        mt = mk["meta"]
        n = r["ops"]
        net = min(r["cyc"]) - base[g]
        row = {"kernel": name, "group": g, "cat": mt.get("cat"), "type": mt.get("type", ""), "op": mt.get("op", ""),
               "d": mt.get("d", ""), "impl": mt.get("impl", ""), "range": mt.get("range", ""), "n": n,
               "cycles_min": min(r["cyc"]), "net": net, "source": "verilator-megaboom-rtl"}
        add_lat = 1.0
        if mt.get("cat") == "dep":
            w32 = mt["type"].endswith("32")
            cl = ctl.get((f"ctl_link{'w' if w32 else ''}_{n}", g))
            row["ctl_link_net"] = cl
            row["per_link"] = round(net / n, 3)
            row["op_lat"] = round((net - (n - 1) * add_lat) / n, 3)
            u = mt.get("unit_cycles")
            if u:
                row["unit_mean_model"] = round(sum(u) / len(u), 3)
                row["unit_min_model"] = min(u)
                row["unit_max_model"] = max(u)
                row["resid_per_op"] = round(row["op_lat"] - sum(u) / len(u), 3)  # = measured core offset
                pred = sum(x + CORE for x in u)
            else:
                L, nu = seq_model(mt["type"], mt["op"], mt["d"])
                row["seq_lat_model"] = L
                row["seq_uops"] = nu
                pred = n * L
            # fixed per-kernel offset beyond ctl_empty; identical for every dep kernel iff the model is exact
            row["F_offset"] = net - pred - (n - 1) * add_lat
            row["op_lat_calib"] = round((net - FOFF - (n - 1) * add_lat) / n, 3)
        elif mt.get("cat") == "ind":
            ci = ctl.get((f"ctl_ind_{n}", g), 0)
            row["ctl_ind_net"] = ci
            row["per_op"] = round(net / n, 3)
            row["per_op_over_skeleton"] = round((net - ci) / n, 3)
            u = mt.get("unit_cycles")
            if u:
                row["unit_mean_model"] = round(sum(u) / len(u), 3)
                row["resid_per_op"] = round(net / n - sum(u) / len(u), 3)
            else:
                L, nu = seq_model(mt["type"], mt["op"], mt["d"])
                row["seq_lat_model"] = L
                row["seq_uops"] = nu
        if mt.get("seq"):
            row["seq_ops"] = " ".join(mt["seq"])
        rows.append(row)
    os.makedirs(a.out, exist_ok=True)
    cols = sorted({c for r in rows for c in r}, key=lambda c: (c not in ("kernel", "group", "cat", "type", "op", "d", "impl", "range", "n"), c))
    with open(os.path.join(a.out, "results.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in sorted(rows, key=lambda r: (r["group"], r["kernel"])):
            w.writerow(r)
    json.dump({"rows": rows, "problems": problems, "groups": meta, "ctl": {f"{k[0]}@{k[1]}": v for k, v in ctl.items()}},
              open(os.path.join(a.out, "results.json"), "w"), indent=1)
    print("problems:", len(problems))
    for p in problems[:40]:
        print("  ", p)
    print("ctl:", {f"{k[0]}@{k[1]}": v for k, v in sorted(ctl.items())})


if __name__ == "__main__":
    main()
