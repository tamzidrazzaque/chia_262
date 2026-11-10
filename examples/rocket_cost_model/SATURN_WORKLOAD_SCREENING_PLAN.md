# Saturn SPEC workload screening plan

## Decision

Continue the Saturn compiler experiment without waiting for a Rocket/Saturn RTL
repair. The current FPGA image is usable for workloads whose scalar and
stock-GCC auto-vectorized binaries both pass correctness. `648.exchange2_s`
remains a preserved, excluded case because its auto-vectorized binary triggers
the known replay/MulDiv correctness failure.

This is a scoped study of Saturn-compatible SPEC workloads. It is not a claim
that the current image is correct for all SPEC programs.

## Workload pool

Use only licensed SPEC CPU2017 workloads. Do not create synthetic substitutes.
Start with the workload families already used or named in the BOOM main-branch
campaign:

- `605.mcf_s`
- `625.x264_s`
- `631.deepsjeng_s`
- `641.leela_s`
- `600.perlbench_s`
- `602.gcc_s`
- `623.xalancbmk_s`

The initial batch should be small and predeclared. A workload is eligible only
if its stock-GCC build actually contains RVV instructions and passes all
correctness gates. The list is a screening pool, not a promise that every
workload will vectorize or run on Saturn.

`648.exchange2_s` remains the documented excluded control. Do not alter its
source, input, ELF, or hardware identity to make it pass.

## Per-workload roles

For each candidate workload, create a separate private identity and retain the
same role structure:

| Role | Definition | Gate |
| --- | --- | --- |
| 1 | Unchanged SPEC source, scalar GCC build | Correct SPEC output and clean execution |
| 2 | Same source and input, stock GCC RVV auto-vectorization | Correct SPEC output, RVV audit, clean execution |
| 3 | Same source, Saturn-aware cost-model candidate | Compare only after roles 1 and 2 pass |

Role 3 is an iterative loop (`3.1`, `3.2`, ...). Each candidate changes only
the declared compiler cost-model fields. Source, input, compiler identity,
ISA/ABI, runtime, FPGA image, and measurement protocol remain fixed.

We are not starting roles 4–5 in this screening phase. Private hand-vectorized
source optimization can be revisited after the compiler-cost loop has a valid
workload set.

## Stages

### Stage 0: local Saturn simulation (no F2)

Start with the exact pinned Chipyard/Saturn/Rocket revisions and the matching
Saturn configuration in a local Chipyard Verilator simulation. This stage is a
development screen, not an FPGA performance claim:

1. Compile the scalar and stock-GCC RVV versions from the unchanged SPEC
   source.
2. Confirm that the role-2 ELF actually contains RVV instructions.
3. Run both binaries functionally in the local Saturn simulator.
4. Require exact SPEC output and a clean simulator exit.
5. Collect target `mcycle`/`minstret` only as local screening data; never use
   host Verilator wall time as performance.
6. Preserve the simulator revision, generated RTL/configuration identity,
   compiler identity, ELF hashes, input identity, and output checks.

Only workloads whose role 1 and role 2 pass Stage 0 move to private FireSim
staging. A local pass does not prove F2 equivalence, but it prevents spending
F2 time on workloads that already fail functionally or do not vectorize.

### Stage A: private build and static screening

For every workload:

1. Build role 1 and role 2 from the unchanged licensed source if the exact
   Stage-0 artifacts are not already available.
2. Record complete compiler, flags, ISA, ABI, source, and input identities.
3. Inspect the final role-2 ELF and assembly.
4. Reject the workload from vector cost-model evaluation if role 2 contains no
   meaningful RVV code.
5. Keep all licensed files and binaries outside Git.

### Stage B: functional correctness

1. Run SPEC's official test input under the pinned QEMU/user-mode validation
   path.
2. Require the exact expected output and a clean exit.
3. Reject role 2 if it crashes, produces an output mismatch, or lacks a complete
   validation record.
4. Preserve rejected evidence and classify it as a platform/workload
   compatibility result, not a performance result.

### Stage C: one F2 pilot pair

Only workloads passing Stages A and B enter hardware:

1. Build separate private guest plans for roles 1 and 2.
2. Reuse the accepted Saturn AGFI/driver/Linux environment.
3. Run one fresh scalar/auto-vectorized pilot pair with identical inputs and
   platform settings.
4. Require VLEN=256 confirmation, exact output, clean shutdown, target cycles,
   and raw private evidence.
5. Do not interpret QEMU or host emulation time as performance.

If either role fails, quarantine that workload and do not start role 3 for it.

### Stage D: candidate loop

For each workload with a valid role-1/role-2 pair:

1. Freeze the role-2 compiler and measurement identity.
2. Propose one bounded Saturn-aware cost-model change.
3. Build an immutable candidate compiler and ELF.
4. Run QEMU correctness and static RVV/ISA audits.
5. Run one fresh F2 candidate measurement.
6. Compare target cycles against the same workload's frozen role 2.
7. Retain negative, unchanged, rejected, and successful candidates.

Increase repetitions only after a candidate is correct and materially
different. Do not pool timings across workloads or treat a candidate that
avoids a crash as a speedup over a failed baseline.

## Interpretation rules

- A passing workload demonstrates compatibility for that workload only.
- A failing workload is not silently dropped; its failure rate is part of the
  Saturn platform result.
- A cost model that avoids a known-bad vectorization may be useful, but it must
  be described as compatibility-aware code generation unless the baseline is
  also correct and performance-comparable.
- No aggregate SPEC score or universal Saturn claim is allowed.
- Results remain non-compliant research measurements, not official SPEC
  submissions.

## Stop conditions

Stop a workload before F2 if:

- role 2 does not generate RVV code;
- QEMU correctness fails;
- output/reference hashes do not match;
- compiler, ISA, input, or image identity is incomplete.

Stop the screening campaign if the first predeclared batch yields no workload
with a valid role-1/role-2 pair. At that point the hardware image needs repair
or the experiment's scope must be revisited; do not keep adding arbitrary
workloads.

## Immediate next actions

1. Prepare the exact pinned local Saturn Verilator configuration and toolchain.
2. Compile and run the first small SPEC batch locally, beginning with
   `605.mcf_s`, `625.x264_s`, `631.deepsjeng_s`, and `641.leela_s`.
3. Report which workloads pass local correctness and contain real RVV code.
4. Only then have the manager prepare private role-1/role-2 bundles for the
   eligible workload set.
5. Run Stage A and Stage B; do not launch F2 until the static and QEMU gates
   pass.
6. Run one F2 pilot pair for the first eligible workload.
7. Start role 3 only after that workload's pair is valid.

The existing `648.exchange2_s` diagnosis, manager lane, and private evidence
remain unchanged and are not overwritten by this screening campaign.
