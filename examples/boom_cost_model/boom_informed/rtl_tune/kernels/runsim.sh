#!/bin/bash
# runsim.sh <variant>...  : run build/<v>/rt.elf on the MegaBoomV3Config Verilator RTL sim
# (cycle-exact core, SimDRAM). One ELF per process; caller keeps <=4 concurrent.
H=$(cd "$(dirname "$0")" && pwd)
SIM=/scratch/trazzaque/megaboom-hw/verilator/simulator-chipyard.harness-MegaBoomV3Config
export LD_LIBRARY_PATH=/scratch/trazzaque/megaboom-hw/verilator/lib
mkdir -p $H/results
for v in "$@"; do  # v = build subdir name (A, B, A-al, ...)
  ( cd $H/results && sha256sum $H/build/$v/rt.elf > $v.elf.sha256 && \
    /usr/bin/time -v nice -n 5 timeout 14400 $SIM +permissive +max-cycles=5000000 +permissive-off $H/build/$v/rt.elf > $v.log 2> $v.stderr; echo "rc=$?" >> $v.stderr ) &
done
wait
