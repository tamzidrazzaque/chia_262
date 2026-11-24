#!/bin/bash
# build.sh <variant: base|A|B|C|D>  -> build/<v>/rt.elf (+ kern.s, rt.dump)
set -euo pipefail
H=$(cd "$(dirname "$0")" && pwd)
R=$(dirname "$H")
MB=/scratch/trazzaque/SLICE/boom-research/microbench/common
BM=/scratch/trazzaque/riscv-gnu-local/bin
v=$1
if [ "$v" = base ]; then CC=/home/eecs/trazzaque/spec2017-research/toolchain/bin/riscv64-unknown-linux-gnu-gcc
else CC=$R/compilers/$v/bin/riscv64-unknown-linux-gnu-gcc; fi
# LEGACY=1 reproduces the original ELFs (harness main in .text.startup, linked AFTER the kernels,
# so main's address and fetch alignment shifted with kernel size: a layout confound found in review).
# Default (review fix): harness compiled with -fno-reorder-functions -falign-functions=64 so main sits in
# .text BEFORE kern.o at a fixed address, and link_fixed.ld puts data at a fixed 64 KiB-aligned address.
if [ -n "${LEGACY:-}" ]; then HX=""; LD=$MB/link.ld; SUF=""; else HX="-fno-reorder-functions -falign-functions=64"; LD=$H/link_fixed.ld; SUF="-h2"; fi
O=$H/build/$v${ALIGN:+-al}$SUF; mkdir -p $O
# ALIGN=1: every kernel function starts on a 4 KiB boundary (layout control: identical
# functions then sit at identical page offsets in every variant ELF)
KFLAGS="${ALIGN:+-falign-functions=4096 }-O2 -march=rv64gc -mabi=lp64d -mcmodel=medany -ffreestanding -fno-pic -fno-builtin -fno-stack-protector -fno-asynchronous-unwind-tables -fno-unwind-tables -Wall"
$CC $KFLAGS -S $H/kern.c -o $O/kern.s
$CC $KFLAGS -c $H/kern.c -o $O/kern.o
# harness: fixed bare-metal GCC 16.1, identical for all variants
$BM/riscv64-unknown-elf-gcc -O2 -march=rv64gc -mabi=lp64d -mcmodel=medany -ffreestanding -fno-builtin -fno-common -nostdlib -nostartfiles -Wall $HX -c $H/harness.c -o $O/harness.o
$BM/riscv64-unknown-elf-gcc -march=rv64gc -mabi=lp64d -mcmodel=medany -nostdlib -nostartfiles -T $LD -Wl,--no-relax -Wl,--no-warn-rwx-segments -static -o $O/rt.elf $MB/crt.S $O/harness.o $O/kern.o -lgcc
$BM/riscv64-unknown-elf-objdump -d $O/rt.elf > $O/rt.dump
sha256sum $O/rt.elf
