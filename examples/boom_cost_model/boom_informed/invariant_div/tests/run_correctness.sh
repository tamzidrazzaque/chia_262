#!/usr/bin/env bash
# Runs the QEMU correctness campaign (results in results/).  Max 6 parallel.
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
Q=${QEMU:-/home/eecs/trazzaque/spec2017-research/qemu/root/usr/bin/qemu-riscv64-static}
R=$HERE/results; mkdir -p $R; rm -f $R/*.txt
jobs=()
for v in O2f O3f O1f Osf O2p O2fmask O2none; do
  jobs+=("$v edge")
  jobs+=("$v exh 1 65536")
  jobs+=("$v rand 10000000 0 0x1234567$((RANDOM%10))")
  jobs+=("$v shapes 3000")
done
# deep runs on the main variant: divisors 1..2^22 exhaustive, 10^9 random checks
step=$(( (1<<22) / 6 ))
for i in 0 1 2 3 4 5; do lo=$((i*step+1)); hi=$(( i==5 ? (1<<22) : (i+1)*step )); jobs+=("O2f exh $lo $hi"); done
jobs+=("O2f rand 1000000000 0 0xC0FFEE")
jobs+=("O3f rand 300000000 0 0xBEEF")
printf '%s\n' "${jobs[@]}" | xargs -P${PAR:-6} -I{} bash -c 'set -- {}; v=$1; shift; out='$R'/$v.$(echo "$@" | tr " " "_").txt; { echo "cmd: test.$v $*"; /usr/bin/time -f "wall=%es" '$Q' '$HERE'/build/test.$v "$@"; echo "rc=$?"; } >$out 2>&1'
echo "== summary"; grep -H "phase=" $R/*.txt | sed "s#$R/##"
echo "== failures"; grep -L "rc=0" $R/*.txt; grep -h MISMATCH $R/*.txt | head
