#!/usr/bin/env bash
# Run the microbenchmark ELFs on a simulator and parse the console output.
#
#   ./run.sh <simulator> [--spike] [--source LABEL] [--out DIR] [-j N]
#            [--timeout SEC] [--] [elf ...]
#
# Examples
#   ./run.sh /path/to/sims/verilator/simulator-chipyard.harness-MegaBoomV3Config \
#            --source verilator-megaboomv3 -j 4
#   ./run.sh /scratch/trazzaque/riscv-isa-sim-local/bin/spike --spike   # functional only
#
# Extra simulator arguments go in $SIM_ARGS, placed before the ELF, e.g.
#   SIM_ARGS="+permissive +max-cycles=20000000 +permissive-off" ./run.sh ...
# (chipyard Verilator: "+permissive ... +permissive-off" brackets plusargs; the
#  ELF must be the last argument; HTIF tohost/fromhost console is used).
# For FireSim, copy the ELFs to the run farm and capture the uartlog/stdout;
# then run:  python3 parse.py --source firesim-f2-megaboom --out DIR <logs...>
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ $# -ge 1 ] || { sed -n 2,20p "$0"; exit 1; }
SIM="$1"; shift
SPIKE=0; SOURCE=""; OUT=""; JOBS=1; TMO=0
while [ $# -gt 0 ]; do
  case "$1" in
    --spike) SPIKE=1; shift ;;
    --source) SOURCE="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    -j) JOBS="$2"; shift 2 ;;
    --timeout) TMO="$2"; shift 2 ;;
    --) shift; break ;;
    *) break ;;
  esac
done
ELFS=("$@")
[ ${#ELFS[@]} -gt 0 ] || ELFS=("$HERE"/build/mb_*.elf)
if [ "$SPIKE" = 1 ]; then
  SOURCE="${SOURCE:-spike-functional-NOT-timing}"
  SIM_ARGS="${SIM_ARGS:---isa=rv64gc_zicntr}"
fi
SOURCE="${SOURCE:-$(basename "$SIM")}"
OUT="${OUT:-$HERE/results/$SOURCE-$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$OUT"
[ "$JOBS" -le 8 ] || { echo "refusing -j > 8 on a shared host" >&2; exit 1; }
echo "simulator=$SIM source=$SOURCE out=$OUT jobs=$JOBS" | tee "$OUT/run.info"
echo "sim_args=${SIM_ARGS:-}" >> "$OUT/run.info"

run_one() {
  local elf="$1" g
  g="$(basename "$elf" .elf)"
  local t0; t0=$(date +%s)
  local rc=0
  if [ "$TMO" -gt 0 ]; then
    timeout "$TMO" "$SIM" ${SIM_ARGS:-} "$elf" > "$OUT/$g.log" 2>&1 || rc=$?
  else
    "$SIM" ${SIM_ARGS:-} "$elf" > "$OUT/$g.log" 2>&1 || rc=$?
  fi
  echo "$g rc=$rc wall_s=$(( $(date +%s) - t0 ))" | tee -a "$OUT/run.info"
}
export -f run_one
export SIM SIM_ARGS OUT TMO
printf '%s\n' "${ELFS[@]}" | xargs -P "$JOBS" -I{} bash -c 'run_one "$@"' _ {}

python3 "$HERE/parse.py" --manifest "$HERE/build/manifest.json" --source "$SOURCE" \
  --out "$OUT" "$OUT"/*.log
