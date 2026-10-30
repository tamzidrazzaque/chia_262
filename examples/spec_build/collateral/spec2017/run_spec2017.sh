#!/bin/bash
# Result wrapper for the pinned Speckle commands. Timing excludes collection.
set -eu
benchmark=$1
shift
[[ "$benchmark" =~ ^[0-9]{3}\.[A-Za-z0-9_]+$ ]] || exit 2
parallel=1
workload=""
suite=$(basename "$0" .sh)
while [ "$#" -gt 0 ]; do
    case "$1" in
        --threads|--copies) parallel=$2; shift 2 ;;
        --workload) workload=$2; shift 2 ;;
        *) echo "Unsupported SPEC2017 run option: $1" >&2; exit 2 ;;
    esac
done
[[ "$parallel" =~ ^[1-9][0-9]*$ ]] || exit 2
[[ -z "$workload" || "$workload" =~ ^[0-9]+$ ]] || exit 2
output=${CHIA_SPEC_OUTPUT_DIR:-/output}
mkdir -p "$output"
output=$(cd "$output" && pwd)
workdir=$PWD
script=run.sh
label=$benchmark
if [ -n "$workload" ]; then
    script=run_workload${workload}.sh
    label=${benchmark}_${workload}
fi

run_one() {
    local directory=$1 name=$2 copy=$3 rc=0
    cd "$directory"
    echo 'name,RealTime,UserTime,KernelTime,copy' > "$output/$name.csv"
    /usr/bin/time -a -o "$output/$name.csv" -f "$label,%e,%U,%S,$copy" \
        "./$script" > "$output/$name.out" 2> "$output/$name.err" || rc=$?
    echo "$rc" > "$output/$name.status"
    if [ "${CHIA_CAPTURE_OUTPUTS:-0}" = 1 ]; then
        # Preserve compare.cmd and files for native SPEC specdiff validation.
        # Collection failure is recorded separately and must also fail the job.
        local collected=0
        # The pinned br-base BusyBox tar has no gzip (-z) support.
        tar -cf "$output/$name.run.tar" . || collected=$?
        echo "$collected" > "$output/$name.collection-status"
        [ "$collected" = 0 ] || rc=$collected
    fi
    return "$rc"
}

case "$suite" in
    intspeed)
        export OMP_NUM_THREADS=$parallel
        run_one "$workdir/$benchmark" "$label" 0
        ;;
    intrate)
        export OMP_NUM_THREADS=1
        pids=()
        rc=0
        for ((i=0; i<parallel; i++)); do
            # Independent files: Speckle's hardlinks can alias writable outputs.
            cp -a "$workdir/$benchmark" "$workdir/copy-$i"
            run_one "$workdir/copy-$i" "${label}_$i" "$i" &
            pids+=("$!")
        done
        for pid in "${pids[@]}"; do
            wait "$pid" || rc=$?
        done
        exit "$rc"
        ;;
    *) echo "Unsupported SPEC2017 suite: $suite" >&2; exit 2 ;;
esac
