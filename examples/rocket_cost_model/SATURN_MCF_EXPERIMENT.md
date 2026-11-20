# Saturn MCF experiment setup

This document freezes the first successful Saturn SPEC workload and defines
the next measurement loop. Licensed SPEC files, binaries, raw UART logs, and
manager receipts remain private on the manager; this file contains only
sanitized identities and aggregate measurements.

## Frozen workload and platform

- Workload: licensed SPEC CPU2017 `605.mcf_s`, `test` input.
- Source variant: unchanged SPEC source.
- Platform: accepted Saturn F2 image, VLEN 256, DLen 128.
- AGFI: `agfi-012e92467d7d2149a`.
- Driver identity: frozen by the accepted platform lock.
- Guest capacity: 2 GiB for each role.
- Correctness output: the executable's `mcf.out`, independently matched to
  the private reference hash.
- Private manager lane: `/home/ubuntu/cs262_compiler/saturn-spec-lane/`.

The pilot was run with fresh images and fresh worker leases. Both roles passed
the VLEN probe, exact output check, clean shutdown, FireSim completion, and
target-cycle collection.

| Role | Compiler/build | Guest s | Whole-boot cycles | Result |
| --- | --- | ---: | ---: | --- |
| 1-scalar | GCC 15.1, `rv64gc`, loop and SLP vectorizers disabled | 101.01 | 105,079,757,477 | correct |
| 2-generic-vector | GCC 15.1, stock RVV auto-vectorization, `rv64gcv_zvbb`, scalable vector bits | 98.65 | 102,720,149,072 | correct |

The single pilot ratio is `role1 / role2 = 1.02297` by target cycles (about
2.24% lower cycles for role 2). This is a pilot observation, not a statistically
stable speedup claim.

## Role definitions

1. **Scalar baseline**: unchanged source; stock pinned GCC with scalar flags
   and vectorizers disabled.
2. **Generic auto-vectorized baseline**: unchanged source and identical input;
   stock pinned GCC RVV flags. GCC is responsible for selecting vector loops.
3. **Saturn-aware candidate loop**: unchanged source/input and the frozen role
   2 compiler identity, with one declared Saturn-aware cost-model change per
   candidate. Candidate IDs are immutable (`3.1`, `3.2`, ...).

No hand-vectorized source, source edits, alternate inputs, QEMU timings, or
synthetic workloads enter this loop.

## Baseline repetition block

The pilot is the accepted correctness gate. Before interpreting a cost-model
candidate, collect a small order-balanced baseline block using fresh runs:

| Pair | First | Second |
| --- | --- | --- |
| B1 | role 1 | role 2 |
| B2 | role 2 | role 1 |
| B3 | role 1 | role 2 |
| B4 | role 2 | role 1 |

Each run must have a new nonce, new image identity, fresh preflight, the same
platform lock, the same official input, and a clean worker lease. A pair is
valid only if both roles pass exact output, VLEN probe, cycle collection, and
clean shutdown. Do not pool a failed pair or replace a failed sample silently.

Report median and per-pair ratios, not only an aggregate mean. Keep whole-boot
cycles as the primary target metric; guest elapsed time is secondary. Host
FireSim wall-clock time is infrastructure overhead and is not a performance
metric.

## Candidate loop

After the baseline block is accepted:

1. Freeze role 2 and its baseline evidence.
2. Propose one bounded cost-model edit and record its rationale before build.
3. Build an immutable role `3.N` compiler/ELF outside Git and run the local
   QEMU correctness and RVV/ISA gates.
4. Admit only a complete private bundle with compiler, ISA, invocation, input,
   reference-output, and ELF hashes.
5. Construct a fresh 2 GiB image using the accepted boot binary; verify that no
   protected component changed.
6. Run one fresh F2 candidate sample paired with frozen role 2. Use reversed
   order for successive candidate pairs when possible.
7. Accept a candidate only when correctness and collection pass. Compare target
   cycles to the same-input role-2 sample; retain unchanged and rejected
   candidates as evidence.

The known `648.exchange2_s` replay/MulDiv failure remains excluded. A passing
MCF result demonstrates compatibility for MCF; it does not prove the RTL fix or
universal Saturn correctness.

## Private evidence locations

The successful pilot receipts and collected evidence are retained privately
under the manager's `saturn-spec-lane` tree. The sanitized implementation and
this plan may be committed; no SPEC payload, ELF, raw output, UART log,
credential, or private hostname may be committed.
