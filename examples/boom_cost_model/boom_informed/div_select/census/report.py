#!/usr/bin/env python3
"""Summarize boom_div_select census logs (mode=off: decisions only, no IL change).

  python3 report.py out_O3 [out_O2]  > report.txt

Static counts are [static-gimple] (plugin decisions at GIMPLE, after "optimized").
Dynamic weights, where shown, are [callgrind-x86]-derived line execution counts from
spec-opportunity/joined (x86 gcc 13.3 -O2 binaries, test/train inputs): an ESTIMATE of how
often the RISC-V site executes, not a RISC-V measurement.
Only function names / file:line / counts are printed (no SPEC source text).
"""
import glob
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict

# [review fix] function names may contain spaces (C++ templates, e.g. "f<long int>"): (.+?) not (\S+)
SITE = re.compile(r"^(\S+): SITE (.+?) (\S+):(\d+) (\S+) (div|mod) d=(-?\d+) loop=(-?\d+) depth=(\d+) recur=(\d) "
                  r"range=(.*?) zero_quot=(\d) hw_unit=\[(\d+),(\d+)\] hw_lat_worst=(\d+) seq_lat=(\d+) "
                  r"seq_uops=(\d+)( seq_alt_sign=1)? -> (\w+) \((.*)\)$")
SKIP = re.compile(r"^(\S+): SITE (.+?) (\S+):(\d+) .*skip=(\S+)")
GCC = "/home/eecs/trazzaque/spec2017-research/toolchain/bin/riscv64-unknown-linux-gnu-gcc"
JOINED = "/scratch/trazzaque/SLICE/boom-research/spec-opportunity/joined"
_ooo = {}


def ooo_keeps_div(t, op, d):
    """Does stock GCC 15.1 -O2 -mtune=generic-ooo keep a hardware div for x OP d (x varying)?
    [static-asm] of a one-line function, cached."""
    key = (t, op, d)
    if key in _ooo:
        return _ooo[key]
    base = t.split("(")[0]
    ct = {"u64": "unsigned long", "s64": "long", "u32": "unsigned int", "s32": "int"}[base]
    if "(from8)" in t:
        ct = "unsigned char" if base[0] == "u" else "signed char"
    if "(from16)" in t:
        ct = "unsigned short" if base[0] == "u" else "short"
    src = f"{ct} f({ct} x){{return x {'/' if op == 'div' else '%'} ({ct})({d}LL);}}\n"
    r = subprocess.run([GCC, "-O2", "-march=rv64gc", "-mabi=lp64d", "-mtune=generic-ooo", "-x", "c", "-S", "-o", "-", "-"],
                       input=src, capture_output=True, text=True)
    v = bool(re.search(r"\t(div|divu|divw|divuw|rem|remu|remw|remuw)\t", r.stdout))
    _ooo[key] = v
    return v


def load_dyn():
    dyn = {}
    for f in glob.glob(os.path.join(JOINED, "5*.json")):
        d = json.load(open(f))
        b = d.get("bench")
        size = d.get("size")
        t = d.get("tunes", {}).get("rv_ooo", {})
        for s in t.get("top_sites", []):
            k = (b, os.path.basename(s["file"]), int(s["line"]))
            cur = dyn.get(k)
            if cur is None or size == "train":
                dyn[k] = {"line_exec": s.get("line_exec", 0), "est_dyn": s.get("est_dyn", 0), "size": size,
                          "insn": s.get("insn"), "kind": s.get("kind")}
    return dyn


def parse(outdir):
    rows, skips = [], Counter()
    for log in sorted(glob.glob(os.path.join(outdir, "*.log"))):
        bench = os.path.basename(log)[:-4]
        for line in open(log, errors="replace"):
            line = line.rstrip("\n")
            m = SITE.match(line)
            if m:
                (src, fn, file, ln, t, op, d, loop, depth, recur, rng, zq, hb, hw_, hlat, slat, suops, alt, dec,
                 why) = m.groups()
                rows.append(dict(bench=bench, src=src, fn=fn, file=os.path.basename(file), line=int(ln), type=t, op=op,
                                 d=int(d), loop=int(loop), depth=int(depth), recur=int(recur), range=rng,
                                 varying=rng.startswith("varying"), zero_quot=int(zq), hw_best=int(hb),
                                 hw_worst=int(hw_), hw_lat=int(hlat), seq_lat=int(slat), seq_uops=int(suops),
                                 alt=bool(alt), dec=dec, why=why))
                continue
            m = SKIP.match(line)
            if m:
                skips[(bench, m.group(5))] += 1
    return rows, skips


def summarize(outdir, dyn):
    rows, skips = parse(outdir)
    print(f"\n## {outdir}\n")
    print("Per benchmark ([static-gimple], every div/mod-by-constant GIMPLE statement after inlining; "
          "pow2/trivial divisors and narrow/wide types excluded):\n")
    print("| bench | sites | uniq file:line | ranged (not varying) | range excludes a<d wrap | worst-case HW latency < SEQ (any ctx) | HW decided, latency ctx | "
          "HW decisions total | of which throughput ctx | KEEP (size) | stock generic-ooo keeps div | sites dyn-weighted |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    tot = Counter()
    for b in sorted({r["bench"] for r in rows} | {k[0] for k in skips}):
        R = [r for r in rows if r["bench"] == b]
        uniq = {(r["file"], r["line"], r["op"]) for r in R}
        ranged = sum(not r["varying"] for r in R)
        nozq = sum(not r["zero_quot"] for r in R)
        lat_hw = sum(r["dec"] == "HW" and r["why"].startswith("latency") for r in R)
        cheaper = sum(r["hw_lat"] < r["seq_lat"] for r in R)
        hw = sum(r["dec"] == "HW" for r in R)
        thr_hw = sum(r["dec"] == "HW" and r["why"].startswith("throughput") for r in R)
        keep = sum(r["dec"] == "KEEP" for r in R)
        ooo = sum(ooo_keeps_div(r["type"], r["op"], r["d"]) for r in R)
        dw = sum(1 for r in R if (b, r["file"], r["line"]) in dyn)
        print(f"| {b} | {len(R)} | {len(uniq)} | {ranged} | {nozq} | {cheaper} | {lat_hw} | {hw} | {thr_hw} | {keep} | {ooo} | {dw} |")
        for k, v in (("sites", len(R)), ("uniq", len(uniq)), ("ranged", ranged), ("nozq", nozq), ("cheaper", cheaper), ("lat_hw", lat_hw),
                     ("hw", hw), ("thr_hw", thr_hw), ("keep", keep), ("ooo", ooo)):
            tot[k] += v
    print(f"| **total** | {tot['sites']} | {tot['uniq']} | {tot['ranged']} | {tot['nozq']} | {tot['cheaper']} | {tot['lat_hw']} | {tot['hw']} | "
          f"{tot['thr_hw']} | {tot['keep']} | {tot['ooo']} | |")
    sk = Counter()
    for (b, why), n in skips.items():
        sk[why] += n
    print(f"\nSkipped statements: {dict(sk)}")
    hwrows = [r for r in rows if r["dec"] == "HW"]
    print(f"\n### All HW decisions ({len(hwrows)}) [static-gimple]\n")
    print("| bench | function | file:line | type op d | range | ctx | hw worst lat | seq lat | generic-ooo keeps div | dyn line_exec [callgrind-x86] |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for r in sorted(hwrows, key=lambda r: (r["bench"], r["file"], r["line"])):
        dk = dyn.get((r["bench"], r["file"], r["line"]))
        ctx = r["why"].split("(")[0] + ("(recur)" if r["recur"] else "")
        print(f"| {r['bench']} | {r['fn']} | {r['file']}:{r['line']} | {r['type']} {r['op']} {r['d']} | {r['range'][:80]} | "
              f"{ctx} | {r['hw_lat']} | {r['seq_lat']} | {int(ooo_keeps_div(r['type'], r['op'], r['d']))} | "
              f"{'' if not dk else dk['line_exec']} |")
    ch = [r for r in rows if r["hw_lat"] < r["seq_lat"] and r["dec"] != "HW"]
    print(f"\n### Worst-case HW latency < SEQ latency but NOT decided HW ({len(ch)}) [static-gimple]\n")
    print("| bench | function | file:line | type op d | range | decision (reason) | hw worst lat | seq lat |")
    print("|---|---|---|---|---|---|---|---|")
    for r in sorted(ch, key=lambda r: (r["bench"], r["file"], r["line"])):
        print(f"| {r['bench']} | {r['fn']} | {r['file']}:{r['line']} | {r['type']} {r['op']} {r['d']} | {r['range'][:80]} | "
              f"{r['dec']} ({r['why'][:90]}) | {r['hw_lat']} | {r['seq_lat']} |")
    # hot constant sites from the dynamic join, with the plugin decision
    print("\n### Hot constant-divisor lines in spec-opportunity/joined (rv_ooo top_sites, kind const_nonpow2) "
          "and what boom_div_select decides there\n")
    print("| bench | file:line | line_exec [callgrind-x86] | input | decisions at this line (type op d: range -> DEC) |")
    print("|---|---|---|---|---|")
    for (b, f, ln), v in sorted(dyn.items(), key=lambda kv: -kv[1]["line_exec"]):
        if "const_nonpow2" not in (v["kind"] or ""):
            continue
        R = [r for r in rows if r["bench"] == b and r["file"] == f and r["line"] == ln]
        if not R:
            desc = "(no site in this census: inlined away / other opt level / not a C/C++ int div)"
        else:
            desc = "; ".join(sorted({f"{r['type']} {r['op']} {r['d']}: {'varying' if r['varying'] else r['range'][:80]}"
                                     f" zq={r['zero_quot']} hw{r['hw_lat']}/seq{r['seq_lat']} -> {r['dec']}" for r in R}))
        print(f"| {b} | {f}:{ln} | {v['line_exec']} | {v['size']} | {desc} |")
    return rows


def main():
    dyn = load_dyn()
    print("# boom_div_select SPEC CPU2017 census\n")
    print(__doc__)
    allrows = {}
    for d in sys.argv[1:]:
        allrows[d] = summarize(d, dyn)
    json.dump({d: rows for d, rows in allrows.items()}, open("census_rows.json", "w"))


if __name__ == "__main__":
    main()
