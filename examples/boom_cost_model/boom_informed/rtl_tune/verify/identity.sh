#!/bin/bash
# identity.sh <variant...>: prove which tune each compiler carries.
R=/scratch/trazzaque/SLICE/boom-research/rtl-tune
cd $R/verify
for v in "$@"; do
  if [ $v = base ]; then CC=/home/eecs/trazzaque/spec2017-research/toolchain/bin/riscv64-unknown-linux-gnu-gcc; else CC=$R/compilers/$v/bin/riscv64-unknown-linux-gnu-gcc; fi
  echo "=== $v: $($CC --version | head -1)"
  [ $v = base ] || (cd $R/compilers/$v && sha256sum -c --quiet SHA256SUMS && echo "frontends sha OK")
  $CC -O2 -Q --help=optimizers -x c /dev/null 2>/dev/null | grep -E -- '-f(unroll-loops|sched-pressure|ira-loop-pressure) ' | tr -s ' \t' ' '
  $CC -O2 -Q --help=params -x c /dev/null 2>/dev/null | grep -E 'sched-pressure-algorithm|max-unrolled-insns|max-average-unrolled|max-completely-peeled|unroll-jam-max' | tr -s ' \t' ' '
  $CC -O2 -S sched_probe.c -o probe.$v.s
  $CC -O2 -S -fdump-rtl-sched2 -fsched-verbose=2 sched_probe.c -o /dev/null 2>/dev/null; mv -f sched_probe.c.*r.sched2 probe.$v.sched2 2>/dev/null
  for f in sdiv80 smod1280 sdiv13 udiv10 mul37 mul11 divmod; do
    ops=$(awk -v f="$f:" '$1==f{p=1;next} p&&/^\t\.size/{p=0} p&&/^\t[a-z]/{print $1}' probe.$v.s | tr '\n' ' ')
    echo "  $f: $ops"
  done
  echo "  mulsched: $(awk '$1=="mulsched:"{p=1;next} p&&/^\t\.size/{p=0} p&&/^\t[a-z]/{print $1}' probe.$v.s | tr '\n' ' ')"
  echo "  fpsched:  $(awk '$1=="fpsched:"{p=1;next} p&&/^\t\.size/{p=0} p&&/^\t[a-z]/{print $1}' probe.$v.s | tr '\n' ' ')"
done
