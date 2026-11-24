#!/usr/bin/env bash
# Placement-sensitivity replicas: relink an already built group (build.sh) with
# a padding object (text + bss) before the kernel objects and the variant
# objects rotated, so every variant lands at different PCs / data addresses.
# Code of each variant is byte-identical to the L0 build (same .o files).
#   ./build_layouts.sh <group> <variants...>     -> build/rk_<g>_L{1,2,3}.elf
set -euo pipefail
H=$(cd "$(dirname "$0")" && pwd)
B=$H/build
GCC=/home/eecs/trazzaque/spec2017-research/toolchain/bin/riscv64-unknown-linux-gnu-gcc
BM=/scratch/trazzaque/riscv-gnu-local/bin/riscv64-unknown-elf-gcc
g=$1; shift
vars=("$@")
PADT=(0 72 2120 6200)   # text pad bytes per layout
PADD=(0 200 1096 3080)  # bss pad bytes per layout
for L in 1 2 3; do
  printf '  .section .text.pad,"ax",@progbits\n  .globl rk_pad_text\nrk_pad_text:\n  .skip %d\n  .section .bss.pad,"aw",@nobits\n  .globl rk_pad_bss\nrk_pad_bss:\n  .skip %d\n' ${PADT[$L]} ${PADD[$L]} > $B/pad_L$L.S
  n=${#vars[@]}; objs=()
  for ((i = 0; i < n; i++)); do objs+=($B/${g}_${vars[$(( (i + L) % n ))]}.o); done
  $BM -march=rv64gc -mabi=lp64d -mcmodel=medany -nostdlib -nostartfiles -static -T $H/common/link.ld \
    -Wl,--no-relax -Wl,--no-warn-rwx-segments -o $B/rk_${g}_L$L.elf \
    $H/common/crt.S $B/rk_main.o $B/rk_data_$g.o $B/${g}_tab.o $B/pad_L$L.S "${objs[@]}" -lgcc
  echo "built $B/rk_${g}_L$L.elf order: ${objs[*]##*/}"
done
