#!/bin/bash
while pgrep -u trazzaque -f 'build_spec.sh rt_' >/dev/null; do sleep 30; done
exec /scratch/trazzaque/SLICE/boom-research/rtl-tune/scripts/build_gcc.sh D E
