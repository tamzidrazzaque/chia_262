#!/usr/bin/env bash
# Unit-level RTL simulation of MegaBOOM V3 functional units, cut out of the
# FireSim MegaBOOM elaborated FIRRTL (same Chisel elaboration as the F2 AGFI
# recipe firesim_megaboom_singlecore_no_nic_l2_llc4mb_ddr3).
# Uses firtool + verilator from the READ-ONLY image anishs-chia-f2-driver-cache:19a07f6
# in a throwaway container (docker run --rm; nothing is committed or tagged).
# Inputs go in via a tar on stdin, results come back as a tar on stdout.
# Single-threaded builds (-j1) to be polite on the shared host.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
FIR="$ROOT/src_snapshot/firesim-generated/FireSimMegaBoomV3.fir.gz"
OUT="$HERE/results"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/boom-unit-rtl.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$OUT"

for m in MulDiv PipelinedMultiplier DivSqrtRecF64; do
  python3 -I "$HERE/firrtl_extract.py" "$FIR" "$m" "$WORK/$m.fir"
done
python3 -I "$HERE/gen_vectors.py" "$WORK/muldiv_vectors.txt"
cp "$HERE"/tb_muldiv.cpp "$HERE"/tb_pmul.cpp "$HERE"/tb_fdiv.cpp "$WORK/"

cat > "$WORK/inner.sh" <<'EOS'
set -e
unset LD_PRELOAD
export PATH=/home/ray/chipyard/.conda-env/riscv-tools/bin:/home/ray/chipyard/.conda-env/bin:$PATH
cd /tmp/w
build() {  # $1 = top module, $2 = testbench
  firtool "$1.fir" --disable-all-randomization -o "$1.sv" > "$1.firtool.log" 2>&1
  verilator --cc --exe --build -j 1 -O2 -Wno-fatal --top-module "$1" -Mdir "obj_$1" \
     "$1.sv" "$2" -CFLAGS -O2 > "$1.verilator.log" 2>&1
}
build MulDiv tb_muldiv.cpp
build PipelinedMultiplier tb_pmul.cpp
build DivSqrtRecF64 tb_fdiv.cpp
./obj_MulDiv/VMulDiv muldiv_vectors.txt > muldiv_results.csv 2> muldiv_summary.txt || true
./obj_PipelinedMultiplier/VPipelinedMultiplier > pmul_results.txt 2>&1 || true
./obj_DivSqrtRecF64/VDivSqrtRecF64 > fdiv_results.csv 2> fdiv_summary.txt || true
{ firtool --version; verilator --version; } > tool_versions.txt 2>&1
tar cf - *.csv *.txt *.log MulDiv.sv PipelinedMultiplier.sv
EOS

tar cf - -C "$WORK" . | docker run --rm -i --entrypoint bash anishs-chia-f2-driver-cache:19a07f6 \
  -c 'mkdir -p /tmp/w && cd /tmp/w && tar xf - && bash inner.sh' 2>"$WORK/docker.stderr" \
  | tar xf - -C "$OUT"
grep -v "LD_PRELOAD\|ld.so" "$WORK/docker.stderr" > "$OUT/docker.stderr.txt" || true
tail -5 "$OUT/docker.stderr.txt"
echo "results in $OUT:"; ls -la "$OUT"
cat "$OUT/muldiv_summary.txt" "$OUT/pmul_results.txt" "$OUT/fdiv_summary.txt"
