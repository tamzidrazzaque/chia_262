#!/usr/bin/env bash
# Queue runner: launch each ELF via run_sim.sh when fewer than 4 of my
# rtl-kernels Verilator sims are running (shared host limit).
H=$(cd "$(dirname "$0")" && pwd)
nsim() { ps -u $(id -u) -o comm=,args= | awk '$1 ~ /^simulator-chip/ && /loadmem=build\/rk_/' | wc -l; }
for e in "$@"; do
  until [ $(nsim) -lt 4 ]; do sleep 20; done
  (cd $H && ./run_sim.sh $e) &
  sleep 15
done
wait
