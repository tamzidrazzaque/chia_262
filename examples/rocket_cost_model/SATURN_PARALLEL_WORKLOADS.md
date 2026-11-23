# Parallel Saturn workloads

MCF and NAB use the same `saturn_adaptive_loop.py`, CHIA compiler/proposer tasks,
bundle transport, and `saturn_paired_campaign.py` measurement policy. They have
separate physical F2 workers, manager lanes, Ray manager addresses, private
queues, output directories and measured histories.

## Read-only terminal monitor

On the producer machine, run:

```bash
watch -n 30 'python3 /scratch/trazzaque/Corey/examples/rocket_cost_model/saturn_status.py --config /scratch/trazzaque/spec-loop/status.json'
```

Omit `watch -n 30` for a single snapshot. Add `--local` to skip manager SSH.
The private configuration maps each label to `run` (its loop output directory)
and `manager_config` (its existing private runner configuration). The command
reads state and the active candidate's dispatched campaign; it never launches
tasks, acquires worker leases, changes files or sends signals. Ctrl-C stops
only the display. State age is time since the last state transition, not a
heartbeat or proof that a long measurement is stalled. Recorded state alone
does not establish that a runner process is alive. The live check additionally
reports job-bound guest panics and quiet-output warnings, and displays collected
samples before a pair completes. See `GUEST_HEALTH_INCIDENT.md` for the kernel
panic investigation and panic watchdog recovery policy.

The private monitor config can include a `service` unit name to observe the
producer controller independently of recorded state. An inactive service is
shown as `CONTROLLER STOPPED`. MCF's resumed controller is owned by a user
systemd service, with its prior completed manager feedback verified and carried
forward; it is independent of this terminal. The monitor never starts/stops
that service. NAB's `hold_reason` explains the current diagnostic gate, and its
manager configuration can specify `diagnosis_progress` for live replay status.

Shared GCC preparation is serialized by its existing build lock and publishes
immutable snapshots. FireMarshal commands share a manager-wide lock; FPGA
execution remains parallel on independent physical-worker leases. Generated
SPEC configs publish atomically to support concurrent benchmark readers.

The second worker was checked idle, its SSH host key verified through AWS SSM,
and the accepted SDK/image/driver pair staged. Previous SDK/runtime directories
were preserved. Strict native-manager SSH uses the lane's verified known-hosts
file. No new FPGA image, protected driver, or installed baseline compiler was
rebuilt.

NAB's unchanged-source scalar and stock-vector bundles passed local SPEC/QEMU
and immutable intake checks. Its full ELF audit reports 3,569 static RVV
instructions; the earlier screening regex reported 682 because it counted a
narrower set of mnemonics. Static instruction counts do not establish dynamic
coverage or speedup. CactuBSSN remains an additional locally screened candidate,
requiring its own complete workload contract and hardware baseline gate.

`saturn_workload_baselines.py` runs scalar then vector hardware pilots.
`saturn_activate_workload.py` requires exact baseline bundle, workload, worker,
platform and cycle evidence before starting the existing continuous runner.
NAB receives only its own measured baseline/history. The deployment remains
official test-input screening, with fresh paired controls and confirmation
thresholds before selecting a candidate.

The proposer is pinned to GPT-5.6 Sol/high, following authorization to use an
older working model. A live CLI smoke test passed with the existing login.
GPT-6.2 Sol/high was rejected by the current ChatGPT-based Codex login. Provider
failures record `waiting_for_model_access` and retry without silently switching
models or repeating completed hardware measurements.

Deployment checkpoint (2026-11-22, Pacific): the second-worker NAB scalar
baseline is running, with its vector baseline scheduled immediately afterward.
The activation watcher initially reported `waiting_for_baselines`; it will
admit the continuous runner only after both exact baseline bundles pass. Four
queued NAB profiles can then execute before model-generated proposals are
needed. The resumed MCF runner initially reported `waiting_for_model_access`, preserving
its completed measurements. Both runners use continuous mode without a fixed
candidate count. The deployed regression suite passed 141 tests and 12 subtests.

Subsequent baseline check: NAB scalar passed at 36,937,795,127 whole-boot cycles.
Its vector run exited successfully but two numeric output values differed from
the exact reference, so activation stopped. Subsequent official SPEC comparison
passed: the exact-hash policy was inappropriate for NAB's tolerated numeric
output. See `NAB_OUTPUT_DIAGNOSIS.md` for the evidence and conservative collector
policy. MCF retries now use the explicitly selected GPT-5.6 Sol/high.
