#!/usr/bin/env bash
# run_correct.sh MODE OPT NRAND [PLUGIN_EXTRA]: build shards with boom_div_select mode=MODE (or "none"), run under QEMU.
set -u
H=$(cd "$(dirname "$0")" && pwd)
G=/home/eecs/trazzaque/spec2017-research/toolchain/bin/riscv64-unknown-linux-gnu-gcc
Q=/home/eecs/trazzaque/spec2017-research/qemu/root/usr/bin/qemu-riscv64-static
PL=$H/../plugin/boom_div_select.so
mode=$1; opt=$2; nr=$3; tune=${TUNE:-rocket}
out=$H/correct/out_${mode}_${opt}_${tune}; mkdir -p $out
pa=""; [ "$mode" != none ] && pa="-fplugin=$PL -fplugin-arg-boom_div_select-mode=$mode -fplugin-arg-boom_div_select-verbose=1"
ls $H/correct/shard_*.c | xargs -P 8 -I{} bash -c 'f={}; b=$(basename $f .c); nice -n 5 '"$G"' -'"$opt"' -mtune='"$tune"' -march=rv64gc -mabi=lp64d -static '"$pa"' -o '"$out"'/$b $f 2> '"$out"'/$b.decisions.txt && nice -n 5 '"$Q"' '"$out"'/$b '"$nr"' > '"$out"'/$b.run.txt 2>&1; echo "$b rc=$? $(tail -1 '"$out"'/$b.run.txt) hw=$(grep -c -- "-> HW" '"$out"'/$b.decisions.txt) seq=$(grep -c -- "-> SEQ" '"$out"'/$b.decisions.txt)"'
