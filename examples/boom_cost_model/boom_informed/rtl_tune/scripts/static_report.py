#!/usr/bin/env python3
"""Summarize asmfuncs.py CSVs: per-benchmark totals and hot-function rows.  [static-asm]

  static_report.py --dir static --prefix ABC_ > static/report.txt
"""
import argparse, collections, csv, glob, os

HOT = {
    "505.mcf_r": ["primal_bea_mpp", "price_out_impl", "spec_qsort", "getArcPosition", "master", "switch_arcs",
                  "suspend_impl", "refresh_potential", "arc_compare"],
    "531.deepsjeng_r": ["ProbeTT", "StoreTT", "_Z4evalP", "static_pawn_eval", "_Z5feval", "search", "gen_captures"],
    "541.leela_r": ["uct_select_child", "sort_children", "get_pattern3", "self_atari", "play_random_move"],
    "557.xz_r": ["lzma_encoder_optimum_normal", "lzma_lzma_optimum_normal", "bt_find_func", "bt_skip_func",
                 "lzma_mf_bt4_find", "lzma_decode", "rc_encode", "lzma_crc32", "lzma_crc64", "get_optimum"],
    "500.perlbench_r": ["Perl_pp_modulo", "S_regmatch", "Perl_hv_common", "Perl_runops_standard"],
    "502.gcc_r": ["htab_expand", "htab_find_slot_with_hash", "color_pass", "maybe_hot_bb_p"],
    "525.x264_r": ["mbtree_propagate_cost", "x264_pixel_satd_8x4", "sub16x16_dct", "quant_4x4", "mc_chroma", "x264_macroblock_analyse"],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--prefix", default="ABC_")
    ap.add_argument("--variants", default="A,B,C")
    a = ap.parse_args()
    vs = a.variants.split(",")
    print("[static-asm] objdump of SPEC benchmark objects, GCC 15.1 variants, -O2 -g, rv64gc")
    print("totals per benchmark: insns / div+rem / mulh / mul, and function pairs identical | reordered-same-opcodes | different-opcodes")
    hdr = ["bench", "funcs"] + [f"{v}:{k}" for v in vs for k in ("ninsn", "div", "mulh", "mul")]
    pairs = [(x, y) for i, x in enumerate(vs) for y in vs[i + 1:]]
    hdr += [f"{x}-{y}" for x, y in pairs]
    print("| " + " | ".join(hdr) + " |")
    print("|" + "---|" * len(hdr))
    hot_rows = []
    for path in sorted(glob.glob(os.path.join(a.dir, a.prefix + "*.csv"))):
        bench = os.path.basename(path)[len(a.prefix):-4]
        per = collections.defaultdict(dict)
        for r in csv.DictReader(open(path)):
            per[(r["obj"], r["func"])][r["variant"]] = r
        tot = {v: collections.Counter() for v in vs}
        pc = collections.Counter()
        for k, rec in per.items():
            for v in vs:
                if v in rec:
                    for f in ("ninsn", "div", "mulh", "mul"):
                        tot[v][f] += int(rec[v][f])
            for x, y in pairs:
                if x in rec and y in rec:
                    if rec[x]["text_hash"] == rec[y]["text_hash"]:
                        pc[(x, y, "i")] += 1
                    elif rec[x]["opset_hash"] == rec[y]["opset_hash"]:
                        pc[(x, y, "r")] += 1
                    else:
                        pc[(x, y, "d")] += 1
            for pat in HOT.get(bench, []):
                if pat in k[1]:
                    hot_rows.append((bench, k[1], rec))
        row = [bench, str(len(per))] + [str(tot[v][f]) for v in vs for f in ("ninsn", "div", "mulh", "mul")]
        row += [f"{pc[(x, y, 'i')]}/{pc[(x, y, 'r')]}/{pc[(x, y, 'd')]}" for x, y in pairs]
        print("| " + " | ".join(row) + " |")
    print()
    print("hot functions (ninsn div mulh mul per variant; '=' identical text to A, '~' same opcode multiset as A)")
    for bench, fn, rec in hot_rows:
        cells = []
        for v in vs:
            if v not in rec:
                cells.append(f"{v}:-")
                continue
            r = rec[v]
            tag = ""
            if v != vs[0] and vs[0] in rec:
                tag = "=" if r["text_hash"] == rec[vs[0]]["text_hash"] else ("~" if r["opset_hash"] == rec[vs[0]]["opset_hash"] else "")
            cells.append(f"{v}:{r['ninsn']}/{r['div']}/{r['mulh']}/{r['mul']}{tag}")
        print(f"{bench:16s} {fn[:60]:60s} " + " ".join(cells))


if __name__ == "__main__":
    main()
