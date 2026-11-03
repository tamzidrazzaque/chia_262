#!/usr/bin/env bash
# Run the real zstd CLI; timing labels are meaningful only on verified Rocket.
set -euo pipefail
if [[ $# != 3 ]]; then
    echo 'usage: run_zstd.sh BINARY INPUT_TAR OUTPUT_DIR' >&2
    exit 2
fi
binary=$(realpath "$1")
input=$(realpath "$2")
output=$3
mkdir -p "$output"
if [[ -e "$output/job.status" ]]; then
    echo 'output directory already contains a run' >&2
    exit 2
fi
trap 'status=$?; printf "%s\n" "$status" > "$output/job.status"' EXIT
sha256sum "$binary" "$input" > "$output/inputs.sha256"
"$binary" --version > "$output/version.txt"
uname -a > "$output/kernel.txt"
cat /proc/cpuinfo > "$output/cpuinfo.txt"
cat /proc/meminfo > "$output/meminfo.txt"
# Warm filesystem and executable pages outside the measurement.
"$binary" -q -3 -f "$input" -o "$output/warmup.zst"
"$binary" -q -d -f "$output/warmup.zst" -o "$output/warmup.tar"
cmp "$input" "$output/warmup.tar"
TIMEFORMAT='real %R'
{ time "$binary" -q -3 -f "$input" -o "$output/compressed.zst"; } 2> "$output/compress.time"
{ time "$binary" -q -d -f "$output/compressed.zst" -o "$output/decoded.tar"; } 2> "$output/decompress.time"
cmp "$input" "$output/decoded.tar"
sha256sum "$output/compressed.zst" "$output/decoded.tar" > "$output/outputs.sha256"
printf 'correct\n' > "$output/correctness.txt"
