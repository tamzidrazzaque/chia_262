#!/usr/bin/env bash
# Launch ELFs one by one, keeping at most 4 of MY range-aware-div sims running.
H=$(cd "$(dirname "$0")" && pwd)
mine() {  # simulator processes whose working directory is this directory
  local n=0 p
  for p in $(pgrep -u "$(id -u)" -f simulator-chipyard.harness-MegaBoomV3Config); do
    [ "$(readlink /proc/$p/cwd)" = "$H" ] && n=$((n + 1))
  done
  echo $n
}
for elf in "$@"; do
  while [ "$(mine)" -ge 4 ]; do sleep 20; done
  echo "$(date +%T) launch $elf"
  nohup "$H/run_sim.sh" "$elf" > /dev/null 2>&1 &
  sleep 5
done
wait
