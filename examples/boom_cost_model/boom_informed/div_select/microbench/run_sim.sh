#!/usr/bin/env bash
# run_sim.sh <elf> : one Verilator MegaBoomV3Config sim (cycle-exact RTL), nice 5, log to results/verilator-megaboom-rtl
set -u
H=$(cd "$(dirname "$0")" && pwd)
SIM=/scratch/trazzaque/megaboom-hw/verilator/simulator-chipyard.harness-MegaBoomV3Config
export LD_LIBRARY_PATH=/scratch/trazzaque/megaboom-hw/verilator/lib
elf=$1; g=$(basename "$elf" .elf)
out=$H/results/verilator-megaboom-rtl; mkdir -p "$out"
t0=$(date +%s)
nice -n 5 "$SIM" +permissive +max-cycles=${MAXC:-60000000} +permissive-off "$elf" > "$out/$g.log" 2>&1
rc=$?
echo "$g rc=$rc wall_s=$(( $(date +%s) - t0 )) sha256=$(sha256sum "$elf" | cut -c1-16)" >> "$out/run.info"
