# Rocket + Saturn vector cost-model status

## Executive summary

We established the hardware path and began the planned Rocket-vector compiler
experiment using the published Saturn F2 platform. The platform boots Linux,
reports VLEN=256, and passes directed vector load/add/store checks. The first
real workload, SPEC CPU2017 `648.exchange2_s`, exposed a reproducible
correctness failure in the tested Rocket/Saturn integration. The failure is not
a performance result and no cost-model claim has been made from it.

The manager-side investigation localized the first observed corruption to a
scalar multiply that executes while Saturn is handling vector replay. The
evidence supports a Rocket/Saturn replay-integration defect: an already-issued
iterative scalar MulDiv request can survive replay and write back again. The
exact published image has not been modified or silently replaced.

We can continue with other real workloads in parallel, provided each workload
gets its own correctness-first scalar and auto-vectorized baseline. Passing a
different workload does not prove the current image is universally correct.

## What we set out to measure

The experiment has two controlled loops:

| Role | Meaning | Status |
| --- | --- | --- |
| 1 | Unchanged source, scalar Rocket reference | One valid `exchange2_s` hardware sample |
| 2 | Same unchanged source, stock GCC generic RVV auto-vectorization | Invalid for `exchange2_s`; reproducible hardware fault |
| 3 | Same source and inputs, iterative Saturn-aware compiler cost-model candidates | Not started |
| 4 | One-time private, straightforward source-vectorized derivative | Not started |
| 5 | Iterative optimization of the role-4 vector source | Not started |

Roles 1–3 form the compiler-cost-model loop. Roles 1 and 2 are frozen
baselines; role 3 is the repeated candidate loop. Roles 4–5 form the separate
source-optimization loop. Role 4 is frozen once; role 5 may iterate. A result
from roles 4–5 must be labeled as a private vectorized derivative, not an
official reportable SPEC result.

## Platform and reproducibility work completed

- Selected the published single-core Rocket + Saturn configuration with
  VLEN=256 and DLEN=128.
- Verified the exact Saturn AGFI/driver pair and the matching FireSim/Chipyard
  revisions used by the accepted image.
- Booted Linux on the F2 worker and confirmed the VLEN-256 full/tail probe.
- Passed directed vector load/add/store checks and clean shutdown checks.
- Built the manager-side private intake, staging, image verification,
  preflight, worker locking, collection, and fail-closed execution checks.
- Constructed and verified 2-GiB guests without rebuilding protected trigger,
  boot, kernel, driver, or FPGA components.
- Kept SPEC files, binaries, raw UART/core/debug logs, credentials, and other
  licensed/private artifacts outside Git.
- Used paired fresh-run identities and rejected runs with missing output or
  incorrect evidence rather than treating manager success as workload success.

## `exchange2_s` evidence

Role 1, the scalar build, completed successfully on F2. The accepted run
collected target cycles, guest timing, clean shutdown, and the expected output.

Role 2 used the unchanged frozen executable produced by stock GCC with generic
RVV auto-vectorization. Three fresh hardware attempts reproduced the same
failure:

- VLEN-256 probe passed.
- The program reached PC `0x11e80`, a strided vector load.
- The process terminated with SIGSEGV.
- `s.txt` was empty, so every attempt was correctly rejected.
- No role-2 performance sample or speedup was accepted.

The manager then performed bounded diagnostics using private copies of the
diagnostic launcher and ELF; the frozen role-2 ELF itself remained unchanged.
At the first directly observed address-chain divergence (`0x11e84`):

```text
instruction: mul a2,a2,a3
QEMU result: 0x510
FPGA result: 0x5100
```

The FPGA result is consistent with repeated application of the multiply. Two
controls distinguish the behavior:

| Diagnostic variant | QEMU | FPGA |
| --- | ---: | ---: |
| Original destination-dependent multiply | `0x510` | `0x5100` |
| Replace multiply with `addi` | `0x145` | `0x145` |
| Multiply from a stable source register | `0x510` | `0x510` |

The scalar register state, vector configuration, and stack-resident step needed
to calculate the address were matched against QEMU. The final invalid address
was downstream of the corrupted scalar result. This makes GCC generating an
invalid address or QEMU reporting a false fault unlikely.

## Current technical diagnosis

Saturn's vector fault checker can require younger scalar work in Rocket to
replay. Rocket's replay path marks the scalar instruction for replay, but the
tested generated RTL derives the iterative MulDiv kill signal from a condition
that omits the relevant vector replay/blocking conditions.

The suspected sequence is:

1. Rocket accepts a scalar iterative multiply request.
2. Saturn's vector-side checking causes the owning scalar instruction to
   replay.
3. The accepted MulDiv request is not invalidated.
4. Its response reaches Rocket's long-latency integer writeback path.
5. The replayed read-modify-write multiply consumes the changed destination,
   producing repeated scalar effects.

This is a strong source-level and hardware-control diagnosis, not a
cycle-exact waveform proof. The safe claim is that the published Rocket +
Saturn image/configuration tested here contains a pre-existing integration
correctness defect. We have not claimed that every Saturn revision or every
configuration is affected.

## Why this is not an experiment-side software bug

- The accepted image, driver, boot binary, and protected source revisions were
  not changed by the experiment.
- The frozen role-2 ELF was hash-verified unchanged after diagnostics.
- The SPEC input and expected output were the official private artifacts.
- QEMU ran the exact frozen ELF and produced the correct scalar/address chain.
- Role 1 completed on the same platform.
- The diagnostic `addi` and stable-source controls passed on the same FPGA.

These checks do not prove the entire platform is correct, but they do rule out
the main workload-staging and compiler-substitution explanations.

## Blockers

### 1. The accepted Saturn image is not valid for all mixed workloads

`exchange2_s` cannot currently serve as a valid role-2 baseline. We must not
silently patch its binary, skip its failure, or claim a speedup from rejected
executions.

### 2. A hardware correction requires a new image identity

The likely fix is to cancel/invalidate an accepted iterative MulDiv request when
vector-side replay kills its owning scalar work, and to prevent a stale response
from writing the register file. That requires RTL assertions, a rebuilt image
and matching driver, a new hardware gate, and rerunning the frozen workload.

### 3. The current manager lane is SPEC-specific

The private manager intake and FireMarshal plans currently describe the
`exchange2_s` bundle. A different workload needs its own private bundle or
adapter, manifest, expected-output hash, guest image, and collection contract.
We should not fabricate a replacement workload or reuse the `exchange2_s`
identity.

### 4. Official Saturn examples are not automatically equivalent experiment roles

The Saturn repository contains many real benchmarks, but many are already
hand-vectorized RVV or assembly kernels. They are useful for platform sanity
checks, but they do not by themselves provide a clean scalar-versus-stock-GCC
auto-vectorization comparison.

## Parallel path that is now allowed

While the `exchange2_s` hardware fix is investigated, select one real workload
with a source-level scalar implementation and a measurable auto-vectorized
variant. `vec-jacobi2d` is a promising candidate because its source contains a
scalar `j2d_s` implementation and a separate vector path, although it still
needs a carefully defined stock-GCC auto-vectorization build.

For each candidate workload:

1. Preserve the original source and inputs.
2. Build and validate the scalar version.
3. Build with stock GCC RVV auto-vectorization and verify that vectorization
   actually occurred.
4. Run one paired correctness-first F2 pilot.
5. Collect cycles only after output, VLEN, shutdown, and evidence checks pass.
6. Begin Saturn-aware cost-model candidates only after roles 1 and 2 for that
   workload are both valid.

Any passing workload is evidence for that workload only. Any new crash or
output mismatch becomes a preserved correctness finding, not a performance
sample.

## What has not happened

- No corrected RTL/image has been built or validated.
- No valid `exchange2_s` role-2 measurement exists.
- No role-3 cost-model candidate has been run on F2.
- No role-4/5 source-optimization campaign has started.
- No speedup, cost-model improvement, or cross-workload ranking has been
  claimed.

## Recommended next steps

1. Keep the original Saturn image and all `exchange2_s` evidence immutable.
2. On a development worktree, implement the minimal MulDiv replay-kill fix and
   directed assertions; validate in RTL simulation before any FPGA build.
3. Build a uniquely identified corrected image/driver and repeat the Saturn
   hardware gate plus the three multiply controls.
4. In parallel, stage one additional real workload with scalar and stock-GCC
   auto-vectorized roles using a separate private identity.
5. Run one correctness-first paired pilot for that workload.
6. Resume role 3 only for workloads whose role 2 is correct, and keep all
   rejected executions and negative candidates in the research record.

## Sanitized evidence pointers

- [Vector experiment plan](VECTOR_PLAN.md)
- [Role-2 fault analysis](ROLE2_FAULT_ANALYSIS.md)
- [Replay diagnosis](ROLE2_REPLAY_DIAGNOSIS.md)
- [Manager status](SATURN_MANAGER_STATUS.md)
- [Replay diagnosis JSON](saturn-role2-replay-diagnosis.json)

The corresponding commits and private evidence identities are recorded in the
branch history. Raw licensed artifacts and hardware logs remain private.
