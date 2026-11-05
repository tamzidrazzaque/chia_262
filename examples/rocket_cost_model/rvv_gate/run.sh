#!/bin/sh
mkdir -p /root/rvv-gate-output
uname -a > /root/rvv-gate-output/uname.txt
cat /proc/cpuinfo > /root/rvv-gate-output/cpuinfo.txt
sha256sum /root/rvv-gate-smoke > /root/rvv-gate-output/binary.sha256
/root/rvv-gate-smoke > /root/rvv-gate-output/result.txt 2>&1
status=$?
printf '%s\n' "$status" > /root/rvv-gate-output/status
cat /root/rvv-gate-output/result.txt
printf 'RVV_GATE_EXIT=%s\n' "$status"
sync
