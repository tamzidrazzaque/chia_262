# Rocket-vector research log

This log records the work completed for the `research/rocket-vector-cost-model` branch and the associated feasibility work in the local Corey workspace.

## Workspace and repo state

- Working directory: `/scratch/trazzaque/Corey`
- Repository: `tamzidrazzaque/chia_262`
- Branch: `research/rocket-vector-cost-model` (created from scalar Rocket commit `06b2ee0`)
- Primary working area: `/scratch/trazzaque/Corey/examples/rocket_cost_model/`
- Validation/temporary artifacts are kept in `examples/rocket_cost_model/.vector-validation/` and are ignored by Git

## 1. GitHub and repo setup

- GitHub access was configured for the workspace folder so that GitHub operations could be done from this folder without exposing access outside it.
- The repo was cloned under Corey and inspected.
- The branch used for the vector work was created from the scalar branch as a separate research line.

## 2. Branch comparison and research direction

We reviewed the relevant research directions:

- `research/rocket-scalar-cost-model`: scalar Rocket baseline work
- `handoff/compiler-cost-models-20261030`: compiler/cost-model methodology and measurement patterns

Key conclusions:

- The scalar Rocket target is not a vector target.
- The compiler-cost-model branch provides methodology (compiler snapshots, cost-model discipline, measurement hygiene) but not vector-Rocket evidence.
- The target should not be treated as if scalar Rocket results automatically apply to vector hardware.

## 3. RVV and Hwacha investigation

We reviewed the architectural context for the vector target work:

- RVV = RISC-V Vector Extension (RVV)
- Hwacha = a prior vector architecture effort, but no active Rocket+Hwacha integration was found in the installed Chipyard tree
- The source review did not find a Rocket+Hwacha configuration in the pinned environment
- Therefore, the active path was RVV-based, with Saturn and Ara as candidate Rocket-integrated vector implementations

## 4. Feasibility plan and branch direction

A new plan was drafted for a vector Rocket branch:

- keep the scalar Rocket work separate
- compare candidate vector integrations before selecting a target
- use Saturn as the first functional/elaboration probe because it is a single-core, smaller-width candidate
- keep Ara as a parallel candidate and do not assume equivalence between Saturn and Ara
- treat source-level configuration facts as separate from proven execution and performance facts

The plan file is:

- `examples/rocket_cost_model/VECTOR_PLAN.md`

## 5. Chipyard / container environment and constraints

Important constraints were documented and preserved:

- Do not create a second scratch workspace
- Keep all work inside `/scratch/trazzaque/Corey`
- Do not modify teammate private paths or shared container state
- Keep existing teammate containers untouched
- Use the already-available Chipyard container instead of creating a new checkout

We confirmed the installed container contained the relevant source tree and tooling, including:

- Chipyard revision: `ad07481af487c44c9f0545db39f9c16cabdecc77`
- Rocket Chip revision: `2f1c549d061f7d6e7fd209ff8b322d0940d200b6`
- Ara revision: `96daf15d3c54ac4975ea2bdc869f95bccdf90a1e`
- Saturn revision: `2dae15d16bebe10f413ea39bdd18aa402eb419dd`

Image provenance:

- Local image ID: `sha256:bee6497fe1a35b178421d25d9c0ed647eeb09ee8c9e3a1f3c6c90105b68bc52c`
- Registry RepoDigest: `ghcr.io/ucb-chia/chia-chipyard@sha256:f983966b1cdc1f6c22ab87d276e1ceb5711d73f6e0bb84a8f5a6b2cbf2b9758c`

## 6. Compiler and ISA smoke checks

We added and tested small vector smoke files:

- `examples/rocket_cost_model/vector_compile_smoke.c`
- `examples/rocket_cost_model/vector_zvbb_smoke.S`
- `examples/rocket_cost_model/vector_functional_smoke.S`

Checked using the installed GCC toolchain in the Chipyard container:

- GCC version: `riscv64-unknown-linux-gnu-gcc 13.2.0 (gc891d8dc23e)`
- Compiler flags used included `-march=rv64gcv` and `-march=rv64gcv_zvbb`

Observed facts:

- RVV intrinsic code generation works in the installed toolchain
- `zvbb` assembler smoke succeeded
- ELF attributes and disassembly showed vector instructions, including `vsetvli`, `vle32.v`, `vadd.vv`, `vse32.v`, and `vandn.vv`
- This confirms compiler/assembler code generation only; it does not prove a hardware target executes correctly

## 7. Saturn elaboration and RTL generation

We checked the candidate config `MINV128D64RocketConfig`:

- config: `MINV128D64RocketConfig`
- vector mixin: `WithRocketVectorUnit(128, 64, VectorParams.minParams)`
- result: successful elaboration to FIRRTL and generated Verilog
- generated device tree advertises `zvbb` and `zvl128b`

This was stored under the ignored validation directory and documented in the feasibility notes.

## 8. Functional investigation and boot-path debugging

We then debugged the runtime path. Key findings:

- The default one-hart boot ROM in this harness does not reach the payload; its startup path loops at the single-hart boot ROM logic and waits for extra harts
- The installed Verilator harness uses TSI, not DTM
- `+loadarch` is not supported in this TSI harness, so it was ignored
- The test-only boot-ROM workaround was necessary to get past the default ROM
- The payload ELF must be loaded into memory before the CPU fetches it; direct ELF load via `+loadmem` was required for the successful run

A temporary config was used:

- `SingleHartSaturnSmokeConfig`
- same Rocket/Saturn vector parameters
- only change: boot ROM file overridden to a tiny ROM that jumps to `0x80001000`

## 9. Bare-metal Saturn RVV pass

We fixed the failing test iteratively and eventually ran a passing self-checking Saturn vector payload.

The final successful run used:

- target: `SingleHartSaturnSmokeConfig`
- boot ROM: temporary jump to ELF entry
- ELF load: `+loadmem=/out/vector-loadmem.elf`
- vector state: enabled `mstatus.VS` in the payload
- instructions exercised: `vsetivli`, vector loads, `vadd.vv`, `vandn.vv`, vector stores
- completion signal: `tohost`

Observed final result:

- `*** PASSED *** Completed after 4126 simulation cycles`

This is a successful instruction-level functional check on the Saturn Verilator model.

## 10. Files created and retained

Main project files:

- `examples/rocket_cost_model/VECTOR_PLAN.md`
- `examples/rocket_cost_model/VECTOR_FEASIBILITY.md`
- `examples/rocket_cost_model/vector_compile_smoke.c`
- `examples/rocket_cost_model/vector_zvbb_smoke.S`
- `examples/rocket_cost_model/vector_functional_smoke.S`

Validation artifacts retained under the ignored directory:

- `examples/rocket_cost_model/.vector-validation/`
- `examples/rocket_cost_model/.vector-validation/functional-attempt.txt`
- `examples/rocket_cost_model/.vector-validation/vector-loadmem.elf`
- `examples/rocket_cost_model/.vector-validation/saturn-singlehart-vector-functional-pass.log`
- `examples/rocket_cost_model/.vector-validation/saturn-singlehart-smoke-simulator`

## 11. Status at the first feasibility checkpoint

Status before the later audit and target selection:

- The Saturn bare-metal vector instruction path is functionally verified in the model
- This is not yet a measured performance experiment
- No FireSim image, runtime, application-level software stack, or hardware validation has been completed
- The work was in feasibility / target-selection stage, before performance modeling

## 12. Final note

The documentation for this work is here:

- `examples/rocket_cost_model/RESEARCH_LOG.md`

The primary evidence/status report is here:

- `examples/rocket_cost_model/VECTOR_FEASIBILITY.md`

## 13. Independent approach audit (2026-11-03)

The feasibility artifacts and inherited compiler path were reviewed before
planning a vector application or measurement campaign.

- The retained generated FIRRTL, device tree, JSON, functional ELF, passing
  simulator binary and pass log match their recorded SHA-256 hashes. The pass
  log ends after 4,126 simulated cycles. The source config for the passing
  simulator matches the Saturn vector parameters of `MINV128D64RocketConfig`
  and adds a boot-ROM override. The generated RTL snapshot retained locally is
  for `MINV128D64RocketConfig`, not that exact passing test config.
- The installed GCC 13.2.0 emits RVV intrinsic code, but a simple restricted
  `int` array-add loop compiled with explicit RVV and vectorization flags
  remained scalar; GCC reported that it could not vectorize the loop. GCC 14
  release notes state that RISC-V loop and SLP vectorization were enabled in
  that release. The inherited compiler builder pins GCC 13 and scalar
  `rv64imafdc`, so it is not a ready vector compiler experiment.
- The existing `VECTOR_PLAN.md` was tightened around compiler selection,
  exact target provenance, a correct real application, and a timing-backend
  pilot. A matching FireSim/FPGA flow is required if Verilator cannot run the
  complete SPEC application within a practical budget. No new
  application, performance run, hardware run or compiler-cost candidate was
  completed by this audit.
- Follow-up scope direction: prioritize the BOOM handoff's licensed SPEC
  CPU2017 `648.exchange2_s` train application on vector Rocket, if authorized
  access and a vector-capable Linux guest are available. The scalar Rocket
  handoff records SPEC access as paused. Exchange2 is a shared application;
  its suitability for vector-cost tuning still requires hot RVV code evidence.
  Reuse the handoff's SPEC build, QEMU test, native comparison and target
  measurement stages, adapting only their vector compiler, runtime and target
  identities after checking each stage's assumptions.

## 14. Saturn selection (2026-11-04)

At this point in the trace, the direction became Rocket plus Saturn and
`MINV128D64RocketConfig` was the initial configuration to qualify. Section 16
supersedes that exact target with the upstream REFV256D128 FireSim target; Ara
remains outside the active campaign.
This selects a vector-unit implementation, not a verified Linux SPEC target.
Next, reuse the existing CHIA SPEC build and correctness path for Exchange2,
verify a vector-capable compiler and guest, and qualify an exact Saturn timing
backend. If the initial Saturn configuration fails a required gate, document
the blocker or qualify a different Saturn configuration with a new manifest
and baseline. Do not transfer scalar Rocket or BOOM measurements to it.

## 15. Real unchanged-SPEC roles 1-3 preparation (2026-11-04)

The first loop-A preparation run now passes through CHIA using the licensed
`648.exchange2_s` test workload, not a synthetic benchmark. Roles 1 and 2 were
built and frozen as the scalar and stock-GCC RVV references. Candidate 3.1 was
built from pinned GCC 15.1 source in the recorded Jammy worker and changes only
the generic RVV integer-statement cost from 1 to 2 before attaching that table
to Rocket's tuning profile.

All three final binaries passed SPEC output validation. Role 1 contains no RVV
instructions; role 2 contains 5,780 static RVV instructions; role 3.1 contains
4,310. The role-2 and role-3 ELF hashes differ, establishing application-level
code-generation sensitivity to the bounded edit. This does not establish a
performance improvement: QEMU was used only for correctness and the CHIA
summary deliberately records no performance backend and no Saturn timing.

Implementation and sanitized status are in `spec_vector_baseline.py`,
`vector_cost_model.py`, `roles_123_chia.py`, and `ROLE_123_STATUS.md`. Private
SPEC configs, logs, binaries, candidate frontends, and the full machine-readable
summary remain outside Git in the authorized research directories.

## 16. Upstream FireSim target selection (2026-11-04)

The active measurement target changed from the local MINV128D64 feasibility
probe to upstream `REFV256D128RocketConfig` and its
`FireSimREFV256D128RocketConfig` wrapper. This is a deliberate hardware-target
change to follow the configuration supported by upstream FireSim, not a claim
that the two configurations are equivalent.

The first roles 1-3 run remains valid correctness and compiler-sensitivity
evidence, but it used QEMU VLEN 128 and is not the frozen baseline for the new
target. Future manifests require VLEN 256/DLEN 128 and the exact FireSim config.
The old role-3.1 rationale and target identity are retired from active scoring.
Before measurement, verify the released AGFI, matching driver, Chipyard,
FireSim and Saturn revisions, bridge metadata, memory/platform configuration
and worker. The pinned GCC 15 supports vector-length-agnostic `zvl`/`scalable`
code only; it rejects a fixed `-mrvv-vector-bits=256` option.

## 17. Official Saturn F2 image and driver path found (2026-11-04)

The Chipyard catalog publication at
`f503763b0c702ac3c423e58d8cc9d0975796a8c2` contains the exact single-core
Saturn Rocket target under
`firesim_saturn_REFV256D128_rocket_singlecore_no_nic_l2_llc4mb_ddr3`, with
AGFI `agfi-012e92467d7d2149a`. Its recipe uses
`FireSimREFV256D128RocketConfig`,
`WithAutoILA_FRFCFS16GBQuadRankLLC4MB_BaseF2Config`, and 60 MHz.

AWS subsequently established that the image embeds FireSim
`b7927ea504c501194eaec3e993c415f2270170f8`. Its matching Chipyard build
source is the publication commit's immediate parent,
`19a07f6b8d4d1db81f5561d9aeceb2cdc43407fe`, with Saturn
`dfe75de2a8868d51d42c20612821431a9fcf645e` and Rocket Chip
`55bcad0f59436de98ea510334121de8546b9e9d7`. The catalog does not contain a
`driver_tar`; official FireSim behavior is to build the target-specific host
driver with `firesim builddriver`. The current host has no usable AWS
credentials, but the manager has now verified the AGFI description. The
resulting driver has not been built or accepted yet. Exact evidence and the acceptance steps are recorded in
`saturn-firesim-discovery.json` and `SATURN_FIRESIM.md`.

## 18. Exact source staged and F2-manager handoff prepared (2026-11-04)

An isolated ignored checkout under `.vector-validation/chipyard-f503763b`
verified the processor config, FireSim wrapper, official recipe and catalog
entry. It established the publication state but, as section 19 records, its
post-publication FireSim pin is not the image's driver source. The installed
`ghcr.io/ucb-chia/chia-chipyard:latest` image is older and does not contain the
selected configuration, so it must not build the driver either.

The large source checkout, generated artifacts and licensed inputs remain
outside Git. `SATURN_MANAGER_HANDOFF.md` now gives the agent on the
AWS-authenticated manager the exact read-only AGFI check, clean setup,
`firesim builddriver` command, expected output, evidence requirements, boot
gate and stop conditions.

## 19. Published-image source provenance reconciled (2026-11-05)

The manager correctly stopped when AWS reported FireSim `b7927ea...` rather
than the originally documented `b2211da...`. Upstream history explains the
difference: catalog commit `f503763b...` has parent `19a07f6...`, which pins
the AWS-reported `b7927ea...`. The child commit simultaneously adds the new
AGFI/recipe entries and advances FireSim by one small follow-up commit. Saturn,
Rocket Chip, the FireSim target wrapper and its file hash, and the F2 SDK are
unchanged across the boundary.

The corrected driver build source is therefore Chipyard `19a07f6...` with
FireSim `b7927ea...`; `f503763b...` remains the catalog-publication reference.
The metadata gate is resolved, but no driver build or hardware run has occurred.

## 20. Saturn hardware gate and VLEN-256 baselines completed (2026-11-05)

The manager built and accepted the exact driver, booted Linux on the published
Saturn F2 image, confirmed VLEN 256, passed explicit RVV load/add/store checks,
collected cycle counters, and shut down cleanly. The gate evidence is recorded
in `SATURN_RVV_GATE.md` and `saturn-hardware-gate.json`.

Local preparation then regenerated unchanged-SPEC roles 1 and 2 for the exact
target. A skeptical check found that the original role-2 flag
`-mrvv-vector-bits=zvl` treated Zvl128 as an exact vector length. At VLEN 256
the binary returned an empty `s.txt`, while Exchange2's configured
`specdiff -m` still returned success. The pipeline now uses scalable RVV and
requires an independent exact-output hash. The corrected role-2 binary contains
5,452 static RVV instructions and matches the 855-byte official output at VLEN
256. A deterministic private roles 1/2 handoff archive was created for manager
staging; licensed contents remain outside Git.

## 21. Complete manager bundle contract produced (2026-11-05)

The manager's fail-closed intake correctly quarantined the first combined tar
because it lacked explicit compiler, ISA and validated-invocation sidecars.
The producer now emits one content-addressed private directory per role without
rebuilding either ELF. Each directory binds the exact `exchange2_s 0`
invocation, official inputs and exact output, stock compiler identity, ISA
audit, and original SPEC validation log. Both generated directories pass the
same independent verifier used by manager intake. Their manifest identities
are recorded in `SATURN_SPEC_LANE.md`; transfer and hardware execution remain
pending.
