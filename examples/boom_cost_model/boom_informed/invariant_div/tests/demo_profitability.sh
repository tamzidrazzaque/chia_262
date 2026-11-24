#!/usr/bin/env bash
# Shows the pass firing / not firing as the hardware-model arguments change.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
GCC=${GCC:-/home/eecs/trazzaque/spec2017-research/toolchain/bin/riscv64-unknown-linux-gnu-gcc}
PL=$HERE/../boom_invariant_div.so; O=$HERE/profit; mkdir -p $O
run(){ local tag=$1; shift; local args=""; for a in "$@"; do args="$args -fplugin-arg-boom_invariant_div-$a"; done
  $GCC -march=rv64gc -mabi=lp64d -O2 -fplugin=$PL $args -DPFX=opt_ -S $HERE/shapes.c -o /dev/null -fdump-tree-boom_invariant_div=$O/$tag.dump
  printf "%-28s rewritten_groups=%2d kept=%2d | bounded3:%s u32_div:%s u64_div:%s s64_outerdef:%s\n" "$tag" \
    $(grep -c -- "-> REWRITE" $O/$tag.dump) $(grep -c -- "-> keep" $O/$tag.dump) \
    $(for k in u32_bounded3 u32_div u64_div s64_outerdef; do grep -h "^\[opt_$k\]" $O/$tag.dump | sed -E 's/.*-> (REWRITE|keep).*/\1/' | head -1; done); }
run default
run div32-occ30 div32-occupancy=30
run div32-occ12 div32-occupancy=12
run div32-occ8 div32-occupancy=8
run div64-occ20 div64-occupancy=20
run div64-occ40 div64-occupancy=40
run mul-lat10 mul-latency=10
run u64-setup-extra2000 u64-setup-extra=2000
run min-trips5 min-trips=5
run min-trips50 min-trips=50
