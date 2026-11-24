#!/usr/bin/env bash
# After the main queue has started its last ELF (rk_kt), launch each given ELF
# when fewer than 4 of my rtl-kernels sims are running.
H=$(cd "$(dirname "$0")" && pwd)
nsim() { ps -u $(id -u) -o comm=,args= | awk '$1 ~ /^simulator-chip/ && /loadmem=build\/rk_/' | wc -l; }
for e in "$@"; do
  until { [ -s $H/results/verilator-megaboom-rtl/rk_kt.err ] || [ -f $H/results/verilator-megaboom-rtl/rk_kt.log ]; } && [ $(nsim) -lt 4 ]; do sleep 15; done
  (cd $H && ./run_sim.sh $e) &
  sleep 10
done
wait
