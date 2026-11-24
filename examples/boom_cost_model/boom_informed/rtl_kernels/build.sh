#!/usr/bin/env bash
# Build rtl-kernels ELFs: one ELF per kernel group, each holding every compiler
# variant of that group's kernels (symbols prefixed <variant>_).
#   kernels: linux cross GCC 15.1 -> .o (freestanding, no PIC, medany)
#   link:    bare-metal GCC 16.1 + common/crt.S + common/link.ld + libgcc
#   expect:  checksums from a native x86 build of the same C (host/)
set -euo pipefail
H=$(cd "$(dirname "$0")" && pwd)
GCC=/home/eecs/trazzaque/spec2017-research/toolchain/bin/riscv64-unknown-linux-gnu-gcc
BM=/scratch/trazzaque/riscv-gnu-local/bin/riscv64-unknown-elf-gcc
OBJDUMP=/scratch/trazzaque/riscv-gnu-local/bin/riscv64-unknown-elf-objdump
INV=/scratch/trazzaque/SLICE/boom-research/invariant-div-pass/boom_invariant_div.so
OCC=/scratch/trazzaque/chia_262/examples/boom_cost_model/boom_informed/boom_div_occupancy.so
B=$H/build
mkdir -p $B $H/host
BASE="-O2 -march=rv64gc -mabi=lp64d -mcmodel=medany -ffreestanding -fno-pic -fno-stack-protector \
 -fno-asynchronous-unwind-tables -fno-unwind-tables -ffp-contract=off -fno-math-errno -I$H/common"
declare -A VF
VF[ooo]="-mtune=generic-ooo"
VF[rocket]="-mtune=rocket"
VF[inv]="-mtune=generic-ooo -fplugin=$INV -fplugin-arg-boom_invariant_div-verbose=1"
VF[invf]="-mtune=generic-ooo -fplugin=$INV -fplugin-arg-boom_invariant_div-verbose=1 -fplugin-arg-boom_invariant_div-force=1"
VF[occ66]="-mtune=generic-ooo -fplugin=$OCC -fplugin-arg-boom_div_occupancy-occupancy=66 -fplugin-arg-boom_div_occupancy-verbose=1"
VF[occ1]="-mtune=generic-ooo -fplugin=$OCC -fplugin-arg-boom_div_occupancy-occupancy=1 -fplugin-arg-boom_div_occupancy-verbose=1"

# group:file:variants:entries
GROUPS_DEF=(
 "ka:ka_qsort:ooo rocket inv occ66 occ1:ka_qsort"
 "kb:kb_hash:ooo rocket inv occ66 occ1:kb_ro kb_rw"
 "kc:kc_uct:ooo rocket inv occ66 occ1:kc_uct"
 "kd:kd_kdtree:ooo rocket inv occ66 occ1:kd_kdtree"
 "ke:ke_modc:ooo rocket inv occ66 occ1:ke_chain_s64 ke_indep_s64 ke_chain_u32 ke_chain_s64_4000 ke_indep_s64_4000"
 "kz:kz_cal:ooo:cal_empty cal_fdivs_dep cal_fdivs_ind4 cal_fsqrts_dep cal_fsqrts_ind4 cal_fdivd_dep"
 "kt:kt_trip:ooo inv:$(for k in tc_u64es tc_u64big tc_u32; do for t in 1 2 4 8 32; do printf '%s_T%s ' $k $t; done; done)"
)
ONLY="${1:-}"
$GCC $BASE -mtune=generic-ooo -c $H/common/rk_main.c -o $B/rk_main.o
for def in "${GROUPS_DEF[@]}"; do
  IFS=: read -r g f vars ents <<<"$def"
  [ -n "$ONLY" ] && [ "$ONLY" != "$g" ] && continue
  objs=()
  DD=""; [ $g = kb ] && DD=-DRK_NEED_TT
  $GCC $BASE -mtune=generic-ooo $DD -c $H/common/rk_data.c -o $B/rk_data_$g.o
  for v in $vars; do
    $GCC $BASE ${VF[$v]} -DPFX=${v}_ -S $H/kernels/$f.c -o $B/${g}_$v.s 2> $B/${g}_$v.decisions.txt
    $GCC $BASE ${VF[$v]} -DPFX=${v}_ -c $H/kernels/$f.c -o $B/${g}_$v.o 2>/dev/null
    objs+=($B/${g}_$v.o)
  done
  # host reference checksums
  {
    echo '#include <stdio.h>'; echo '#include "rk.h"'
    for e in $ents; do echo "u64 h_$e(u64 *);"; done
    echo 'int main(void){ u64 tm[2]; rk_data_init();'
    for e in $ents; do echo "  printf(\"$e %016llx\\n\", (unsigned long long)h_$e(tm));"; done
    echo '  return 0; }'
  } > $H/host/${g}_main.c
  gcc -O2 -ffp-contract=off -fno-math-errno -I$H/common -DPFX=h_ $H/host/${g}_main.c $DD $H/common/rk_data.c $H/kernels/$f.c -o $H/host/$g.host -lm
  $H/host/$g.host > $H/host/$g.expect
  {
    echo '#include "rk.h"'
    echo 'typedef struct { const char *k; const char *v; u64 (*fn)(u64 *); u64 expect; } ent_t;'
    echo "const char RK_GROUP[] = \"$g\";"
    for v in $vars; do for e in $ents; do echo "u64 ${v}_$e(u64 *);"; done; done
    echo 'const ent_t RK_TAB[] = {'
    for e in $ents; do
      x=$(awk -v e=$e '$1==e{print $2}' $H/host/$g.expect)
      for v in $vars; do echo "  {\"$e\", \"$v\", ${v}_$e, 0x${x}ULL},"; done
    done
    echo '};'
    echo 'const unsigned RK_N = sizeof(RK_TAB) / sizeof(RK_TAB[0]);'
  } > $B/${g}_tab.c
  $GCC $BASE -c $B/${g}_tab.c -o $B/${g}_tab.o
  $BM -march=rv64gc -mabi=lp64d -mcmodel=medany -nostdlib -nostartfiles -static -T $H/common/link.ld \
    -Wl,--no-relax -Wl,--no-warn-rwx-segments \
    -o $B/rk_$g.elf $H/common/crt.S $B/rk_main.o $B/rk_data_$g.o $B/${g}_tab.o "${objs[@]}" -lgcc
  $OBJDUMP -d $B/rk_$g.elf > $B/rk_$g.dump
  echo "built $B/rk_$g.elf ($(wc -l < $H/host/$g.expect) entries x $(echo $vars | wc -w) variants)"
done
