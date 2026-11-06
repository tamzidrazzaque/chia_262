# Unchanged-SPEC roles 1-3 status

## Active VLEN-256 baselines (2026-11-05)

Roles 1 and 2 have now been regenerated for the selected
`REFV256D128RocketConfig` target using unchanged licensed SPEC CPU2017
`648.exchange2_s` test source and inputs. Both passed a fresh QEMU correctness
run at the target VLEN and an independent exact-output hash check:

| Role | Final ELF SHA-256 | Static RVV instructions | Exact output |
| --- | --- | ---: | --- |
| 1. Scalar reference | `6500e7e82a183d11d5e83b0ff4b3ee79fc709127c849b8c2fca1675307d27e7d` | 0 | 855 bytes, SHA-256 `93c5882eda07b05bf277b4636f8a92cd16bf347e8cf5513fc578b8f60c12506e` |
| 2. Generic vector reference | `933c5062989468d8eba30c72a08dadb2e15bf39dfffff2532f5f2fed5cada541` | 5,452 | same exact reference hash |

Role 2 uses stock GCC 15.1 with `-mrvv-vector-bits=scalable`. The earlier
`zvl` setting was invalid for this deployment: GCC's own source defines it as
treating the Zvl minimum as the exact VLEN. That binary returned immediately
with an empty output at VLEN 256 even though CPU2017's Exchange2 `specdiff -m`
comparison reported success. The experiment now rejects an empty or non-exact
`s.txt` independently of the harness status. The corrected role 2 ran for
269.9 seconds under QEMU VLEN 256 and matched the official reference exactly.

The private deterministic roles 1/2 handoff is retained outside Git at
`/home/eecs/trazzaque/spec2017-research/results/saturn-vlen256-baselines/`
as `saturn-spec-roles-1-2.tar`. Its SHA-256 is
`9c6331dea7f03a6e9364df4305d8ce0dae696ab5f683feb0c37208ce9bdb10ca`.
It contains licensed material and must not be published. The next controlled
step is manager-side intake, FireMarshal staging, and paired role-1/role-2 F2
measurement. Role 3 remains unmeasured and must not be generated or selected
from QEMU timing.

> **Superseded target notice (2026-11-04):** this run used the earlier VLEN
> 128 correctness target. The active campaign now selects upstream
> `REFV256D128RocketConfig` and its `FireSimREFV256D128RocketConfig` wrapper.
> The results below remain compiler-sensitivity evidence, but roles 2 and 3
> are not frozen baselines for the new target and must be regenerated with
> VLEN 256 correctness metadata before hardware measurement.

## Result on 2026-11-04

The first CHIA preparation run for loop A completed for the real licensed SPEC
CPU2017 `648.exchange2_s` test workload. All three roles used unchanged SPEC
source and inputs and passed SPEC's output validation:

| Role | Compiler distinction | Final ELF SHA-256 | Static RVV instructions | Status |
| --- | --- | --- | ---: | --- |
| 1. Scalar reference | GCC 15.1, `rv64gc`, loop and SLP vectorizers disabled | `6500e7e82a183d11d5e83b0ff4b3ee79fc709127c849b8c2fca1675307d27e7d` | 0 | Frozen correctness baseline |
| 2. Generic vector reference | Pinned stock GCC 15.1 RVV cost behavior | `c171ebf51c7a16a96952244a5b8307138d3657465b27b2a010f9e830314f6c72` | 5,780 | Frozen correctness baseline |
| 3.1 Saturn-aware candidate | Only generic RVV `int_stmt_cost` changed from 1 to 2 and attached to Rocket tuning | `f6a8d88f38fddf7831eb387589691cf2e8b781e9588ffb587f2004db6458b790` | 4,310 | Correct and code-generation-sensitive; performance unresolved |

The role-3.1 hypothesis is source-derived: the selected Saturn configuration
has VLEN 128 and a 64-bit datapath, so a full-width vector operation spans two
datapath chunks. This is not a measured Saturn instruction latency. The change
in the final ELF proves that the bounded cost edit affects this application,
but neither fewer RVV instructions nor the QEMU runtime proves improvement.

The private machine-readable summary is retained at
`/home/eecs/trazzaque/spec2017-research/results/saturn-roles-1-3-chia/648.exchange2_s-test-roles-1-3-chia.json`.
It records `performance_backend: null`, `saturn_timing_complete: false`, the
candidate-manifest hash, final ELF hashes, ISA attributes, and aggregate static
instruction counts. Licensed source, binaries, raw outputs, and SPEC logs stay
outside Git.

## Reproducibility boundary

- GCC source is pinned to commit
  `1b306039ac49f8ad91ca71d3de3150a3c9fa792a` (GCC 15.1.0) with a verified
  source-archive hash.
- Candidate frontends are built in the recorded Jammy worker image
  `sha256:02975bda46a6623a6eb03d48f1b1fc9a115d0c69015bf3e4a911d086a0e7e333`
  and saved as immutable, content-addressed snapshots.
- Roles 2 and 3 use identical application source, inputs, target flags, QEMU,
  and output validator. The intended controlled variable is the vector cost
  table attached to GCC's Rocket tuning profile.
- QEMU with VLEN 128 is a functional gate only. No target cycles or target
  performance result have been collected.

## Next gate for the active target

Do not select the old role 3.1 as an optimization. The official image has now
been identified as AGFI `agfi-012e92467d7d2149a`; see `SATURN_FIRESIM.md`.
Next verify its AWS description, build and fingerprint the matching driver from
the pinned source, freeze its memory/platform and worker identities, and
regenerate roles 2 and 3 under the VLEN 256 target metadata. Then measure them
with paired fresh runs and score target cycles. Only exact-target measurements
may accept, reject, or train the next role-3 proposal.
