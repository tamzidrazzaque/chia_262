#!/usr/bin/env bash
# Run rtl-kernels ELFs on the Verilator MegaBoomV3Config simulator (cycle-exact
# core RTL, SimDRAM memory).  +loadmem preloads the ELF into the simulated DRAM
# (TSI loading of even a 20 KB ELF takes > 8 min wall; loadmem ~ seconds).
# At most 4 concurrent sims (shared host), nice 5.
set -euo pipefail
H=$(cd "$(dirname "$0")" && pwd)
S=/scratch/trazzaque/megaboom-hw/verilator/simulator-chipyard.harness-MegaBoomV3Config
export LD_LIBRARY_PATH=/scratch/trazzaque/megaboom-hw/verilator/lib
OUT=$H/results/verilator-megaboom-rtl
mkdir -p $OUT
run1() {
  local e=$1 g; g=$(basename $e .elf)
  local t0=$(date +%s)
  local rc=0
  nice -n 5 timeout 14400 $S +permissive +max-cycles=60000000 +loadmem=$e +permissive-off $e > $OUT/$g.log 2> $OUT/$g.err || rc=$?
  echo "$g rc=$rc wall_s=$(( $(date +%s) - t0 )) sha=$(sha256sum $e | cut -c1-16)" >> $OUT/run.info
}
export -f run1; export S OUT
printf '%s\n' "$@" | xargs -P 4 -I{} bash -c 'run1 "$@"' _ {}
