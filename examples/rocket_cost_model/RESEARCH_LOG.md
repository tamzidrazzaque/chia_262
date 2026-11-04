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

The experiment direction is now Rocket plus Saturn. The initial configuration
to qualify is `MINV128D64RocketConfig`; Ara is outside the active campaign.
This selects a vector-unit implementation, not a verified Linux SPEC target.
Next, reuse the existing CHIA SPEC build and correctness path for Exchange2,
verify a vector-capable compiler and guest, and qualify an exact Saturn timing
backend. If the initial Saturn configuration fails a required gate, document
the blocker or qualify a different Saturn configuration with a new manifest
and baseline. Do not transfer scalar Rocket or BOOM measurements to it.
