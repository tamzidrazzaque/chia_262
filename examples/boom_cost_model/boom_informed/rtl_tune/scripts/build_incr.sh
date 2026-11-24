#!/bin/bash
# After the full build of A in gcc/build-A (source gcc/src-A), build the other variants
# incrementally in the same tree: copy the variant's 5 rendered riscv files over src-A,
# `make -j8 all-gcc` (GCC's move-if-change keeps unchanged generated headers), snapshot
# frontends. Finally restore A's files and rebuild A so build-A again matches A.
# usage: build_incr.sh C B   (A must already be snapshotted)
set -euo pipefail
R=/scratch/trazzaque/SLICE/boom-research/rtl-tune
TC=/home/eecs/trazzaque/spec2017-research/toolchain
FILES="riscv.cc riscv-cores.def riscv-opts.h riscv.md boom.md"
snap() {
  local v=$1 O=$R/compilers/$1 B=$R/gcc/build-A
  mkdir -p $O/frontends $O/bin
  for f in cc1 cc1plus f951 collect2 lto1 lto-wrapper xgcc; do cp -p $B/gcc/$f $O/frontends/; done
  for lang in gcc g++; do
    printf '#!/bin/sh\nexec %s -B%s/frontends/ -mtune=boom "$@"\n' "$TC/bin/riscv64-unknown-linux-gnu-$lang" "$O" > $O/bin/riscv64-unknown-linux-gnu-$lang
    chmod +x $O/bin/riscv64-unknown-linux-gnu-$lang
  done
  (cd $R/gcc/src-$v/gcc/config/riscv && sha256sum $FILES) > $O/SOURCES.sha256
  (cd $O && sha256sum frontends/* > SHA256SUMS)
  grep -q 'HAVE_GAS_CFI_DIRECTIVE 1' $B/gcc/auto-host.h && echo "gas CFI ok $v" || echo "WARNING no gas CFI $v"
}
case "${1:-}" in
  snapA) snap A; exit 0;;
esac
for v in "$@"; do
  for f in $FILES; do cp $R/gcc/src-$v/gcc/config/riscv/$f $R/gcc/src-A/gcc/config/riscv/$f; done
  echo "$(date) start incremental make $v"
  (cd $R/gcc/build-A && nice -n 5 make -j8 all-gcc > make-$v.log 2>&1)
  echo "$(date) done make $v"
  snap $v
done
# restore A sources (pristine copy kept in src-A.orig-riscv)
for f in $FILES; do cp $R/gcc/src-A.orig-riscv/$f $R/gcc/src-A/gcc/config/riscv/$f; done
echo "$(date) start restore make A"
(cd $R/gcc/build-A && nice -n 5 make -j8 all-gcc > make-A-restore.log 2>&1)
echo "$(date) done restore A"
cmp $R/gcc/build-A/gcc/cc1 $R/compilers/A/frontends/cc1 && echo "restored cc1 identical to A snapshot" || echo "restored cc1 differs from A snapshot (timestamps/paths?)"
