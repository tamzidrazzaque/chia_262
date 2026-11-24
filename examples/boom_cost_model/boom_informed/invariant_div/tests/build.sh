#!/usr/bin/env bash
# Build correctness binaries: shapes.c with the plugin in several variants,
# shapes.c at -O0 without plugin as the reference, and the driver.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
GCC=${GCC:-/home/eecs/trazzaque/spec2017-research/toolchain/bin/riscv64-unknown-linux-gnu-gcc}
PL=$HERE/../boom_invariant_div.so
A="-march=rv64gc -mabi=lp64d"
P="-fplugin=$PL"
B=$HERE/build; mkdir -p $B
$GCC $A -O0 -DPFX=ref_ -c $HERE/shapes.c -o $B/ref.o
$GCC $A -O2 -c $HERE/driver.c -o $B/driver.o
declare -A V=(
  [O2f]="-O2 $P -fplugin-arg-boom_invariant_div-force=1"
  [O3f]="-O3 $P -fplugin-arg-boom_invariant_div-force=1"
  [O1f]="-O1 $P -fplugin-arg-boom_invariant_div-force=1"
  [Osf]="-Os $P -fplugin-arg-boom_invariant_div-force=1"
  [O2p]="-O2 $P"
  [O2fmask]="-O2 $P -fplugin-arg-boom_invariant_div-force=1 -fplugin-arg-boom_invariant_div-u32-quot=mask"
  [O2none]="-O2"
)
for v in "${!V[@]}"; do
  D=""; [[ "${V[$v]}" == *fplugin* ]] && D="-fdump-tree-boom_invariant_div=$B/shapes.$v.dump"
  $GCC $A ${V[$v]} -fchecking -DPFX=opt_ -c $HERE/shapes.c -o $B/opt.$v.o $D 2>$B/build.$v.err || { echo "build $v failed"; cat $B/build.$v.err; exit 1; }
  $GCC $A ${V[$v]} -DPFX=opt_ -S $HERE/shapes.c -o $B/shapes.$v.s
  $GCC $A -static $B/driver.o $B/opt.$v.o $B/ref.o -o $B/test.$v
  echo "built $v: $(grep -c REWRITE $B/shapes.$v.dump 2>/dev/null || echo 0) groups rewritten"
done
