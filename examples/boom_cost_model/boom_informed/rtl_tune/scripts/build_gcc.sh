#!/bin/bash
# Build variant GCC frontends (all-gcc) with the compiler-loop configure line; -j8, nice 5.
# usage: build_gcc.sh A [B C ...]
set -euo pipefail
R=/scratch/trazzaque/SLICE/boom-research/rtl-tune
TC=/home/eecs/trazzaque/spec2017-research/toolchain
# target binutils (objdump) must be on PATH, else gcc/configure leaves gcc_cv_objdump empty,
# cfi_advance_working=no and HAVE_GAS_CFI_DIRECTIVE=0 (no gas CFI; same defect as compiler-loop/build)
export PATH=$TC/bin:$PATH
for v in "$@"; do
  S=$R/gcc/src-$v; B=$R/gcc/build-$v; O=$R/compilers/$v
  mkdir -p $B $O/frontends $O/bin
  cd $B
  if [ ! -f Makefile ]; then
    nice -n 5 $S/configure --target=riscv64-unknown-linux-gnu --prefix=$R/gcc/unused-install-$v \
      --with-sysroot=$TC/sysroot --with-pkgversion=g1b306039a --with-system-zlib --enable-shared \
      --enable-tls --enable-languages=c,c++,fortran --disable-libmudflap --disable-libssp \
      --disable-libquadmath --disable-libsanitizer --disable-nls --disable-bootstrap \
      --disable-default-pie --disable-multilib --with-abi=lp64d --with-arch=rv64gc \
      --with-isa-spec=20191213 --with-as=$TC/bin/riscv64-unknown-linux-gnu-as \
      --with-ld=$TC/bin/riscv64-unknown-linux-gnu-ld > configure.log 2>&1
  fi
  echo "$(date) start make $v"
  nice -n 5 make -j8 all-gcc > make.log 2>&1
  echo "$(date) done make $v"
  grep -q 'HAVE_GAS_CFI_DIRECTIVE 1' $B/gcc/auto-host.h || { echo "FATAL no gas CFI $v"; exit 1; }
  for f in cc1 cc1plus f951 collect2 lto1 lto-wrapper; do cp -p gcc/$f $O/frontends/; done
  cp -p gcc/xgcc $O/frontends/xgcc
  for lang in gcc g++; do
    printf '#!/bin/sh\nexec %s -B%s/frontends/ -mtune=boom "$@"\n' "$TC/bin/riscv64-unknown-linux-gnu-$lang" "$O" > $O/bin/riscv64-unknown-linux-gnu-$lang
    chmod +x $O/bin/riscv64-unknown-linux-gnu-$lang
  done
  (cd $O && sha256sum frontends/* > SHA256SUMS)
  grep -q 'HAVE_GAS_CFI_DIRECTIVE 1' $B/gcc/auto-host.h && echo "gas CFI ok $v" || echo "WARNING no gas CFI $v"
done
