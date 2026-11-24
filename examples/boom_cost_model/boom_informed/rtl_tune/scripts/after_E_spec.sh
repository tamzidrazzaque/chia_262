#!/bin/bash
cd /scratch/trazzaque/SLICE/boom-research/rtl-tune
while ! grep -q "gas CFI ok E\|FATAL" gcc/build-DE.log; do sleep 30; done
while pgrep -u trazzaque -f 'run_spec.sh rt_C|run_perl_train.sh rt_[BC]' >/dev/null; do sleep 30; done
cd spec && ./build_spec.sh rt_D rt_E
for v in D E; do ./run_spec.sh rt_$v; ./fix_x264_compare.sh rt_$v > x264fix_rt_$v.txt 2>&1; ./run_perl_train.sh rt_$v; done
