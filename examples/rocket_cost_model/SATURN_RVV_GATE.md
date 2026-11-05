# Saturn Linux/RVV hardware gate

**Passed on F2, 2026-11-05.** The public Saturn AGFI
`agfi-012e92467d7d2149a` booted the pinned FireMarshal Linux guest using accepted
driver `5d3353ea8e6bf2891555da3d7b29122b1143a2e3d8c61a2a55741f1fd0bc94bd`.
`vlenb` was 32 bytes: **VLEN 256**. One Rocket processor exposed V in Linux.

The test in `rvv_gate/smoke.c` uses explicit RVV assembly with automatic
vectorizers disabled. It loads two arrays, adds them and stores the result.
Independent scalar comparisons check unsigned wraparound, eight active lanes,
three active lanes and untouched store sentinels. It rejects missing Linux V,
wrong VLEN, incorrect results and non-increasing target cycle counters.
`run.sh` saves the executable hash, CPU information, result and exit status.
`validate.py` rejects incomplete collection, failed manager/guest status, wrong
binary identity, wrong ISA/core count/VLEN, failed checks and missing shutdown.

Observed target cycle CSR values were 3,719,172,933 and 3,719,173,590.
The self-check exited 0, Linux printed `reboot: Power down`, and FireSim reported
`*** PASSED *** after 3770962967 cycles`. The manager returned 0 and collected
all expected outputs. These are correctness-gate counters, not performance labels
for SPEC or the compiler cost model.

## Evidence and private artifacts

`saturn-hardware-gate.json` records sanitized hashes and accepted checks, linked
to the immutable driver-acceptance receipt. The discovery manifest points to
both records and sets `hardware_execution_verified=true`.

Private local root:
`/home/ubuntu/cs262_compiler/saturn-manager-artifacts/rvv-gate-001`.
It contains the overlay/executable, workload description, build and manager logs,
deployed-pair check, validated receipt and a copy of collected outputs.
The first failed SSH lookup attempt is preserved under `attempt001`.

Native results directory under the pinned Chipyard checkout:
`sims/firesim/deploy/results-workload/2026-11-05--23-36-33-saturn-rvv-gate-001-gate001`.
The workload is installed as `deploy/workloads/saturn-rvv-gate-001.json`, and its
base/boot image is in `software/firemarshal/images/firechip/saturn-rvv-gate-001`.
Raw logs, images, binaries, credentials and worker identity remain outside Git.

## How the manager ran it

The exact manager source and environment are documented in
`SATURN_MANAGER_HANDOFF.md`. The compile used its original cross GCC 13.2.0:

```bash
riscv64-unknown-linux-gnu-gcc -O2 -static -march=rv64gcv -mabi=lp64d \
  -fno-tree-loop-vectorize -fno-tree-slp-vectorize \
  examples/rocket_cost_model/rvv_gate/smoke.c -o OVERLAY/root/rvv-gate-smoke
```

Copy `rvv_gate/run.sh` to `OVERLAY/root/rvv-gate-run.sh`. The FireMarshal workload
inherits `br-base.json`, uses the overlay, runs `sh /root/rvv-gate-run.sh` and
collects `/root/rvv-gate-output`. The pinned Linux configuration enables
`CONFIG_RISCV_ISA_V` and its default userspace enablement. `marshal build` and
`marshal install` completed successfully.

Only one existing authorized idle worker was used. The private runtime config
`deploy/config_runtime_saturn_gate.yaml` selects `ExternallyProvisioned`, that
one host, `one_fpga_spec`, FPGA mode, the accepted Saturn hardware catalog entry,
one node, the installed workload and termination on completion. This provisions
no additional cloud instances. The worker remains running and idle with Saturn
loaded for follow-on SPEC work.

The private native-manager adapter lives at
`/home/ubuntu/cs262_compiler/saturn-manager-artifacts/native-manager.py`, with
`run-native-gate.sh` and `execute-gate.py` alongside it. It invokes the pinned
FireSim manager rather than the scalar-target adapter. It uses the already
verified SDK policy and skips optional interactive debug services. A worker-side
`flock` on `/home/ubuntu/rocket-runtime.lock` spans setup and execution.

One integration issue was resolved: pinned FireSim sets
`env.disable_known_hosts=True` inside main. The adapter wraps Fabric connection
creation to force existing known-host verification and rejection of unknown keys,
using the owner's known-hosts file. No SSH policy or security-group changes were
made. Do not fix this issue by disabling host-key verification.

Before boot, the adapter required the deployed executable hash, loaded AGFI,
shell and resolved worker dependencies to match. It ran native `infrasetup` and
`runworkload` with finite host timeouts, then checked completion, collected
artifacts and confirmed that no simulation process/screen remained. On timeout,
inspect the physical worker before retrying; a timeout does not stop a detached
simulation automatically.

## Next work

The platform gate is complete. Begin SPEC role preparation and output validation
on this exact target before collecting real baseline timings. Keep original and
unchanged-rebuild controls, role flags and workload identities distinct. This
smoke supplies no SPEC correctness, speedup or adaptive-search evidence.
