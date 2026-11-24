#!/usr/bin/env python3
"""Per-function static comparison of RISC-V objects built by several compilers.

  asmfuncs.py --objdump OBJDUMP --variant A=dirA --variant B=dirB ... --out prefix

Each dir is a SPEC build dir (all *.o inside are disassembled). Functions are keyed by
(object basename, symbol). For each function: instruction count, multiset of opcodes,
div/rem counts, mulh counts, mul counts, and a normalized text hash (addresses and
pc-relative targets stripped) so 'identical schedule' can be tested exactly.
Output: <prefix>.csv (one row per function x variant) and <prefix>_summary.json.
Only function names / counts are written (no source text).
"""
import argparse, collections, csv, glob, hashlib, json, os, re, subprocess

FUNC = re.compile(r"^[0-9a-f]+ <(.+)>:$")
INSN = re.compile(r"^\s+[0-9a-f]+:\s+(?:[0-9a-f]{4,8}\s+)?(\S+)\s*(.*)$")
DIV = {"div", "divu", "divw", "divuw", "rem", "remu", "remw", "remuw"}
MULH = {"mulh", "mulhu", "mulhsu"}
MUL = {"mul", "mulw"}


def norm_operands(ops):
    ops = re.sub(r"<[^>]*>", "", ops)
    ops = re.sub(r"\b[0-9a-f]{5,}\b", "ADDR", ops)
    return ops.strip()


def disasm(objdump, path):
    out = subprocess.run([objdump, "-d", "--no-show-raw-insn", "-M", "no-aliases,numeric", path],
                         capture_output=True, text=True).stdout
    funcs, cur = {}, None
    for line in out.splitlines():
        m = FUNC.match(line)
        if m:
            if m.group(1).startswith(".L"):   # local/debug-line labels (.LM*, .L*) stay in the function
                continue
            cur = m.group(1)
            funcs[cur] = []
            continue
        m = INSN.match(line)
        if m and cur in funcs:
            op = m.group(1)
            op = op[2:] if op.startswith("c.") else op   # RVC form follows reg alloc; count base op
            funcs[cur].append((op, norm_operands(m.group(2))))
    return funcs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--objdump", required=True)
    ap.add_argument("--variant", action="append", required=True, help="NAME=builddir")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    data = {}
    for spec in a.variant:
        name, d = spec.split("=", 1)
        per = {}
        for o in sorted(glob.glob(os.path.join(d, "**", "*.o"), recursive=True)):
            rel = os.path.relpath(o, d)
            for f, insns in disasm(a.objdump, o).items():
                per[(rel, f)] = insns
        data[name] = per
    names = [s.split("=", 1)[0] for s in a.variant]
    keys = sorted(set().union(*[set(v) for v in data.values()]))
    rows = []
    summ = {n: collections.Counter() for n in names}
    pair = collections.Counter()
    for k in keys:
        rec = {}
        for n in names:
            ins = data[n].get(k)
            if ins is None:
                continue
            ops = collections.Counter(i[0] for i in ins)
            h = hashlib.sha1("\n".join(f"{o} {r}" for o, r in ins).encode()).hexdigest()[:16]
            ms = hashlib.sha1(json.dumps(sorted(ops.items())).encode()).hexdigest()[:16]
            r = {"obj": k[0], "func": k[1], "variant": n, "ninsn": len(ins),
                 "div": sum(ops[x] for x in DIV), "mulh": sum(ops[x] for x in MULH),
                 "mul": sum(ops[x] for x in MUL), "fmadd": sum(v for o, v in ops.items() if o.startswith(("fmadd", "fmsub", "fnmadd", "fnmsub"))),
                 "branches": sum(v for o, v in ops.items() if o.startswith("b")),
                 "text_hash": h, "opset_hash": ms}
            rec[n] = r
            rows.append(r)
            for f in ("ninsn", "div", "mulh", "mul", "fmadd", "branches"):
                summ[n][f] += r[f]
            summ[n]["funcs"] += 1
        for i, x in enumerate(names):
            for y in names[i + 1:]:
                if x in rec and y in rec:
                    p = f"{x}-{y}"
                    pair[p + ":common"] += 1
                    if rec[x]["text_hash"] == rec[y]["text_hash"]:
                        pair[p + ":identical"] += 1
                    elif rec[x]["opset_hash"] == rec[y]["opset_hash"]:
                        pair[p + ":same_opcodes_reordered"] += 1
                    else:
                        pair[p + ":different_opcodes"] += 1
    with open(a.out + ".csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    json.dump({"totals": {n: dict(c) for n, c in summ.items()}, "pairs": dict(pair)},
              open(a.out + "_summary.json", "w"), indent=1)
    print(json.dumps({"totals": {n: dict(c) for n, c in summ.items()}, "pairs": dict(pair)}, indent=1))


if __name__ == "__main__":
    main()
