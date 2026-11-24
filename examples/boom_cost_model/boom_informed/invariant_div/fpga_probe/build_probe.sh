#!/usr/bin/env bash
# Builds inv_div_probe.elf (bare metal, HTIF, 0x80000000).  The lead runs it on
# MegaBOOM; this script only builds it and checks it functionally on spike.
set -euo pipefail
H=$(cd "$(dirname "$0")" && pwd)
GCC=${GCC:-/home/eecs/trazzaque/spec2017-research/toolchain/bin/riscv64-unknown-linux-gnu-gcc}
F="-march=rv64gc -mabi=lp64d -O2 -ffreestanding -mcmodel=medany -fno-pic -fno-stack-protector"
$GCC $F -DPFX=base_ -c $H/probe_kernels.c -o $H/k_base.o
$GCC $F -DPFX=inv_ -fplugin=$H/../boom_invariant_div.so -fplugin-arg-boom_invariant_div-verbose=1 -c $H/probe_kernels.c -o $H/k_inv.o 2> $H/k_inv.decisions.txt
$GCC $F -DPFX=inv_ -fplugin=$H/../boom_invariant_div.so -S $H/probe_kernels.c -o $H/k_inv.s
$GCC $F -DPFX=base_ -S $H/probe_kernels.c -o $H/k_base.s
$GCC $F -c $H/probe_main.c -o $H/main.o
$GCC $F -nostdlib -nostartfiles -static -T $H/probe.ld $H/main.o $H/k_base.o $H/k_inv.o -lgcc -o $H/inv_div_probe.elf
sha256sum $H/inv_div_probe.elf
