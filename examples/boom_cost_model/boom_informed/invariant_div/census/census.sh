#!/usr/bin/env bash
# Compile-only census of where boom_invariant_div fires in SPEC CPU2017 intrate.
# Reads SPEC sources in place; writes NO object/asm (-o /dev/null); keeps only
# the plugin's decision lines (function names + counts).  -O3 as in riscv_*.cfg.
set -uo pipefail
H=$(cd "$(dirname "$0")" && pwd)
SPEC=/home/eecs/trazzaque/spec2017-research/install/benchspec/CPU
TB=/home/eecs/trazzaque/spec2017-research/toolchain/bin
PL=$H/../boom_invariant_div.so
COMMON="-march=rv64gc -mabi=lp64d -O3 -DSPEC -DSPEC_CPU -DNDEBUG -DSPEC_LP64 -DSPEC_LINUX -fplugin=$PL -fplugin-arg-boom_invariant_div-verbose=1 ${EXTRA_PLUGIN_ARGS:-}"
declare -A FL=(
 [500.perlbench_r]="-DSPEC_LINUX_X64 -D_DEFAULT_SOURCE -DPERL_CORE -I. -Idist/IO -Icpan/Time-HiRes -Icpan/HTML-Parser -Iext/re -Ispecrand -DDOUBLE_SLASHES_SPECIAL=0 -DSPEC_AUTO_SUPPRESS_OPENMP -D_LARGE_FILES -D_LARGEFILE_SOURCE -D_FILE_OFFSET_BITS=64 -fgnu89-inline"
 [502.gcc_r]="-I. -I./include -I./spec_qsort -DSPEC_502 -DSPEC_AUTO_SUPPRESS_OPENMP -DIN_GCC -DHAVE_CONFIG_H -fgnu89-inline"
 [505.mcf_r]="-Ispec_qsort -DSPEC_AUTO_SUPPRESS_OPENMP"
 [520.omnetpp_r]="-Isimulator/platdep -Isimulator -Imodel -DWITH_NETBUILDER -DSPEC_AUTO_SUPPRESS_OPENMP"
 [523.xalancbmk_r]="-DAPP_NO_THREADS -DXALAN_INMEM_MSG_LOADER -I. -Ixercesc -Ixercesc/dom -Ixercesc/dom/impl -Ixercesc/sax -Ixercesc/util/MsgLoaders/InMemory -Ixercesc/util/Transcoders/Iconv -Ixalanc/include -DPROJ_XMLPARSER -DPROJ_XMLUTIL -DPROJ_PARSERS -DPROJ_SAX4C -DPROJ_SAX2 -DPROJ_DOM -DPROJ_VALIDATORS -DXML_USE_INMEM_MESSAGELOADER -DSPEC_AUTO_SUPPRESS_OPENMP"
 [525.x264_r]="-Ildecod_src/inc -Ix264_src -Ix264_src/extras -Ix264_src/common -DSPEC_AUTO_SUPPRESS_OPENMP -DSPEC_AUTO_BYTEORDER=0x12345678"
 [531.deepsjeng_r]="-DSMALL_MEMORY -DSPEC_AUTO_SUPPRESS_OPENMP"
 [541.leela_r]="-I. -DSPEC_AUTO_SUPPRESS_OPENMP"
 [548.exchange2_r]="-DSPEC_AUTO_SUPPRESS_OPENMP"
 [557.xz_r]="-DSPEC_AUTO_BYTEORDER=0x12345678 -DHAVE_CONFIG_H=1 -DSPEC_MEM_IO -DSPEC_XZ -DSPEC_AUTO_SUPPRESS_OPENMP -I. -Ispec_mem_io -Isha-2 -Icommon -Iliblzma/api -Iliblzma/lzma -Iliblzma/common -Iliblzma/check -Iliblzma/simple -Iliblzma/delta -Iliblzma/lz -Iliblzma/rangecoder"
)
OUT=$H/out${TAG:-}; mkdir -p $OUT
for b in "${!FL[@]}"; do
  src=$SPEC/$b/src
  # Multi-executable benchmarks (525.x264_r: x264_r + ldecod_r + imagevalidate_525) define %sources per
  # executable; use only the benchmark's own executable (${b#*.}), not the validation-only tools.  [review fix]
  srcs=$(cd $SPEC/$b/Spec && perl -e 'our %Config=(byteorder=>"12345678"); do "./object.pm"; my @s=@sources; @s=@{$sources{$ARGV[0]}} if !@s && exists $sources{$ARGV[0]}; print join("\n", @s)' "${b#*.}" 2>/dev/null)
  [ -z "$srcs" ] && srcs=$(cd $src && find . -name '*.c' -o -name '*.cc' -o -name '*.cpp' -o -name '*.F90' | sed 's#^\./##')
  echo "$srcs" > $OUT/$b.sources
  (cd $src && echo "$srcs" | xargs -P${PAR:-8} -I{} bash -c 'f={}; case $f in *.c) C="'$TB'/riscv64-unknown-linux-gnu-gcc -std=gnu99 -fno-strict-aliasing";; *.cc|*.cpp|*.cxx) C="'$TB'/riscv64-unknown-linux-gnu-g++ -std=c++03";; *.F90|*.f90) C="'$TB'/riscv64-unknown-linux-gnu-gfortran";; *) exit 0;; esac; $C '"$COMMON ${FL[$b]}"' -S -o /dev/null $f 2>&1 | grep -E "^\[|^boom_invariant_div|error:" | sed "s#^#$f: #"' ) > $OUT/$b.log 2>&1
  echo "$b files=$(echo "$srcs" | wc -l) errors=$(grep -c 'error:' $OUT/$b.log) groups=$(grep -c '\] loop' $OUT/$b.log) rewrite=$(grep -c -- '-> REWRITE' $OUT/$b.log) keep=$(grep -c -- '-> keep' $OUT/$b.log)"
done | tee $OUT/summary.txt
