# Unchanged-SPEC roles 1-3 status

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

## Next gate

Do not select role 3.1 as an optimization yet. First connect and qualify an
exact `MINV128D64RocketConfig` Saturn timing backend that can execute the same
workload identity, or run a bounded pilot proving that the selected application
path is tractable. Then measure frozen role 2 and role 3.1 with paired fresh
runs and score target cycles. Only exact-target measurements may accept,
reject, or train the next role-3 proposal. Expand from test to train only after
the timing pilot passes its wall-time and provenance gates.
