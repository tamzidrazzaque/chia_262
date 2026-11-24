#!/usr/bin/env bash
# spike commit trace (functional) -> trace_model.py (timing models). [model]
H=$(cd "$(dirname "$0")/.." && pwd)
S=/scratch/trazzaque/riscv-isa-sim-local/bin/spike
for g in "$@"; do
  nice -n 5 $S --isa=rv64gc_zicntr -l --log-commits $H/build/rk_$g.elf 2>&1 >/dev/null | \
    nice -n 5 python3 $H/model/trace_model.py - $H/build/${g}_tab.c $H/results/model/$g.json > $H/results/model/$g.txt
done
