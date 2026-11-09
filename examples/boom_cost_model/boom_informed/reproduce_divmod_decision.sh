#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
GCC="${GCC:-/home/eecs/trazzaque/spec2017-research/toolchain/bin/riscv64-unknown-linux-gnu-gcc}"
OUT="${OUT:-$HERE/asm}"
mkdir -p "$OUT"
"$GCC" -v 2>&1 | tail -n 3
for tune in rocket generic-ooo xiangshan-nanhu; do
  "$GCC" -O3 -march=rv64gc -mabi=lp64d -static -mtune="$tune" \
    -S -o "$OUT/div_vs_mulh.$tune.s" "$HERE/div_vs_mulh.c"
  echo "==== $tune udiv_const ===="
  sed -n '/^udiv_const:/,/[[:space:]]*\.size[[:space:]]*udiv_const/p' "$OUT/div_vs_mulh.$tune.s"
done
echo
echo "Expected: rocket -> mulhu; generic-ooo/xiangshan-nanhu -> divu."
