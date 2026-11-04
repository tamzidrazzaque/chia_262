# Rocket vector cost-model research plan

## Purpose and relationship to the other branches

This plan is for the separate `research/rocket-vector-cost-model` branch. It
starts from `research/rocket-scalar-cost-model` at `06b2ee0`, so the scalar
Rocket setup and implementation remain available as reference and must not be
silently repurposed as a vector target.

Use the two prior research lines for different things:

- `research/rocket-scalar-cost-model` provides the Rocket-specific baseline
  setup, compiler reproducibility work, application packaging, hardware
  provenance checks, and lessons about what is and is not yet verified. Its
  selected single-core Rocket image is `rv64imafdc` and has no vector unit.
  Its scalar timings, target manifest, and scalar compiler edits are not vector
  evidence. See [the Rocket handoff](../../research/ROCKET_HANDOFF.md),
  [source-derived target notes](TARGET_NOTES.md), and
  [image discovery](IMAGE_DISCOVERY.md).
- `handoff/compiler-cost-models-20261030` (handoff snapshot `fd6bff3`) provides
  the iterative measured-cost-model method, immutable compiler snapshots,
  correctness checks, explicit measurement identities, and paired
  confirmation practices. Its MegaBOOM/SPEC measurements and cost tables are
  not Rocket-vector evidence and must not be used as vector training data. See
  the [compiler research handoff](../boom_cost_model/research/HANDOFF.md) and
  [experiment plan](../boom_cost_model/EXPERIMENT_PLAN.md).

Reuse general software and experimental patterns only after checking that they
apply. Keep scalar Rocket, vector Rocket, and MegaBOOM configurations,
compiler identities, caches, timing labels, and conclusions separate.

## Audit result and immediate handoff

The existing plan remains the research plan. An independent artifact and
compiler audit identified the following gates for the next agents:

| Claim | Current evidence | Decision |
| --- | --- | --- |
| Saturn instruction execution | The retained ELF, simulator and log hashes match their manifest; a self-checking RVV+Zvbb test passes on `SingleHartSaturnSmokeConfig`. | Accept only for the tested bare-metal instructions and test boot path. |
| Standard Saturn target | `MINV128D64RocketConfig` elaborated and its FIRRTL contains Saturn modules; the passing simulator uses a second config that overrides the boot ROM. | Retain exact generated RTL and a build manifest for whichever config becomes the measurement target. |
| Installed compiler | GCC 13.2.0 emits RVV intrinsics, but a simple `int` array-add loop compiled with `-O3 -ftree-vectorize -march=rv64gcv_zvbb` remained scalar. | Do not use this compiler as an assumed automatic-vectorization baseline. |
| Existing compiler builder | `cost_model.py` pins GCC 13 and edits scalar `rocket_tune_info`; the Rocket application path fixes `rv64imafdc` and disables vectorization. | Build a separately pinned vector compiler path after proving a relevant vector cost hook. |
| Application and measurement | No SPEC run on vector Rocket or vector FireSim image/driver is verified. The scalar Rocket handoff says licensed SPEC access was paused. | Reuse the existing SPEC build and correctness stages first; select the target timing backend after a wall-time and provenance pilot. |

Work in this order:

1. **Choose the compiler question.** For automatic vectorization research,
   evaluate a pinned GCC release with RISC-V loop/SLP vectorization (GCC 14
   introduced it) or a pinned LLVM toolchain. Confirm on a simple source loop
   and then on the chosen application, using vectorization diagnostics and
   disassembly. If the application instead uses explicit intrinsics, state that
   the experiment concerns code generation or scheduling of explicit RVV code;
   show that a bounded model edit changes the final binary before measuring.
   If neither route yields code sensitivity, stop the compiler-cost search.
2. **Qualify the selected Saturn target.** Continue with Saturn as the chosen
   vector unit, using `MINV128D64RocketConfig` as the initial configuration
   because it already has an instruction pass. Record the
   exact simulator config, boot ROM, memory initialization, RTL, simulator,
   source revisions and hashes. Verify the configuration and Linux software
   path needed by SPEC before fixing the final measurement configuration.
   Report a blocker if Saturn cannot support that path; do not switch vector
   units within this campaign.
3. **Reuse the SPEC path.** Check authorized CPU2017 access. Build
   `648.exchange2_s` test/train through `start_workload` with a vector compiler
   prefix and explicit ISA flags, then use the existing QEMU and native SPEC
   comparisons for correctness. Audit the final ELF and guest vector-state
   support. The scalar Rocket handoff records SPEC access as paused. If
   Exchange2 has no hot RVV code, retain it as a shared workload and screen
   another licensed SPEC application for vector-cost tuning.
4. **Choose a timing backend with a pilot.** The Saturn test ROM remains an
   instruction smoke. Try a bounded application test on exact Saturn RTL only
   if its Linux boot path works, and record host wall time per simulated target
   cycle. Full SPEC train on Verilator is conditional on that pilot being
   tractable. Otherwise obtain an exact matching vector FireSim image/driver
   and verified worker, following the handoff's F2 measurement path. Run an
   unchanged-compiler application baseline before setting the search budget.

[GCC 14 release notes](https://gcc.gnu.org/gcc-14/changes.html) document the
RISC-V vectorizer milestone. The probe source, flags and observed output are recorded
in [the feasibility report](VECTOR_FEASIBILITY.md).

## Reuse the handoff's SPEC pipeline

Keep the working SPEC stages from `handoff/compiler-cost-models-20261030` and
adapt their target-specific edges:

| Existing entry point | Reuse for vector Rocket | Required check or change |
| --- | --- | --- |
| `examples/spec_build/spec_sw_build_loop.py:start_workload` | Select `648.exchange2_s`, test/train inputs, compiler prefix and flags; compose the existing FireMarshal workload. | Verify the pinned Speckle flags, final linked ISA and runtime libraries; validate that the `br-base` Linux kernel saves/restores vector state. |
| `examples/boom_cost_model/tasks.py:qemu_stage` and `validate_stage` | Boot test images, collect statuses and run native SPEC comparisons with the licensed installation. | Confirm the QEMU CPU and guest expose RVV; keep QEMU time out of target performance labels. |
| `chia/chipyard/spec_validation.py` and `measurements.py` | Retain completion, native comparison, workload identity and cache validation. | Include exact vector target, compiler and backend in identities; count only fresh runs as repeats. |
| `examples/boom_cost_model/optimize.py:Experiment` and `focused_campaign.py` | Reuse workload preparation, validation, finite search and confirmation structure. | The existing `Experiment` constructs a MegaBOOM bitstream; `RocketExperiment` currently fixes scalar flags and scalar hardware. Add vector-specific target checks and a selected timing adapter before dispatch. |
| `examples/boom_cost_model/tasks.py:fpga_stage` | Use its dispatch and collection pattern if a vector FireSim image exists. | Require matching vector image, generated driver, source revisions, shell and an idle worker; the BOOM and scalar Rocket images cannot execute RVV. |

The handoff's workflow is: pinned compiler and SPEC build, QEMU test input,
native output comparison, target train timing, then fresh confirmation and
held-out inputs. Keep that ordering. The exact target may be an RTL simulator
only if the pilot establishes feasible full-application runtime; otherwise use
a verified vector FireSim backend or stop before performance search.

## Scope decision: Saturn for Rocket vector research

**Selected implementation:** Saturn attached to one Rocket core. The initial
configuration is `MINV128D64RocketConfig`, with 128-bit vector length, 64-bit
datapath width and `VectorParams.minParams`. Its exact simulator and eventual
measurement configuration must still pass the Linux, SPEC and timing gates.

The installed Chipyard container also contains another Rocket-integrated RVV
configuration:

- Ara wrapper `V4096Ara2LaneRocketConfig`, with a 4096-bit vector length and
  two Ara lanes. Ara is documented here for provenance and is outside the
  active experiment.

The checked-in scalar Rocket image does not contain Saturn. The active
container's Chipyard, Rocket Chip, and Saturn revisions differ from the scalar
handoff pins, so this branch will use and record the installed versions as a
separate target instead of claiming equivalence. Saturn elaboration and a
bare-metal RVV+Zvbb smoke now pass in Verilator using a test-only one-hart boot
config; the selected Saturn configuration has no verified application runtime
or performance image yet. Exact revisions, build and functional evidence, and
remaining gaps are recorded in
[the feasibility report](VECTOR_FEASIBILITY.md).

Saturn is the chosen direction because its Rocket configuration is present in
the pinned source and a bare-metal instruction test passes. Chipyard's
[Saturn documentation](https://chipyard.readthedocs.io/en/stable/generators/saturn/)
describes virtual-memory and precise-trap support, which the existing Linux
SPEC path needs. Chipyard's
[Ara integration documentation](https://chipyard.readthedocs.io/en/stable/generators/ara/)
describes limitations in those features. These documentation claims must be
checked against the exact pinned Saturn design and guest; the current smoke
does not prove Linux application support. The source review did not establish
a Rocket+Hwacha integration in the pinned tree.

Bind all compiler, manifest and measurement identities to the exact Saturn
configuration before building the cost model. If a different Saturn parameter
set is required for SPEC, record it as a new exact target with its own baseline.

Do not treat `-march=rv64gcv`, a compiler flag, or a configuration name as
proof that matching hardware and software exist. If Saturn cannot be built and
executed with a verified software stack, stop at documented offline feasibility
and report the blocker. Never label the existing scalar Rocket image as
vector-capable.

## Phase 0: establish target feasibility

1. Verify the selected Saturn Rocket configuration in the installed Chipyard
   and Saturn revisions. Record its vector parameters, supported extensions,
   virtual-memory and trap behavior, and required Linux runtime support from
   source and executable checks. Confirm whether `MINV128D64RocketConfig`
   can support the SPEC path or document a new exact Saturn configuration.
2. Find an exact matching simulation or FPGA target. Record its configuration,
   ISA/extension, vector parameters (such as VLEN/ELEN when applicable),
   memory/platform settings, exact simulator RTL/binary and boot inputs, or
   FPGA image and driver/build provenance, and execution-worker identity.
   Distinguish source-derived facts from verified build facts and measured facts.
3. Check whether the image and driver are available and compatible with the
   execution environment. Do not assume the public scalar Rocket F2 image or
   the MegaBOOM image is reusable.
4. Define a target-specific manifest and preflight. Reject mismatched hardware,
   toolchain, runtime, or worker identities before building or measuring.
5. Decide the fallback and stop condition if no matching simulator or image,
   runtime, or supported toolchain is available. Offline compiler experiments
   may continue only if clearly labeled as code-generation feasibility.

**Gate:** do not begin target performance work until the vector ISA is proven by
the pinned configuration and by an executable test on the matching target.

## Phase 1: prove toolchain and application correctness

1. Establish a vector-capable compiler and runtime for the selected
   implementation. Pin compiler source/build identity, assembler, linker,
   sysroot, ABI, ISA flags, vector options, runtime libraries, and application
   build inputs. Build and inspect a minimal vector executable before the real
   application. Require a demonstrated simple-loop automatic-vectorization
   pass if that is the research question. The installed GCC 13.2.0 failed that
   probe; its intrinsic pass is a distinct capability. Preserve the scalar
   compiler snapshot as a separate baseline.
2. Make an unchanged/reproducible compiler build check before allowing cost
   edits. Confirm compiler wrappers and actual compiler executables select the
   intended vector target; a manifest label alone is insufficient.
3. Prioritize the same licensed SPEC CPU2017 application and train input used
   in the BOOM handoff: `648.exchange2_s`. Reuse the benchmark and input
   identities and native correctness comparison, while compiling a new
   executable for the selected vector target. Inspect its baseline hot code.
   If it has no relevant RVV work, keep it as a shared workload and
   choose a second licensed SPEC workload only after showing hot vector code.
   The scalar Rocket handoff records paused SPEC access; verify the current
   authorization, vector-capable Linux guest and worker installation before
   implementation. The existing zstd path is a fallback if licensed SPEC
   access is unavailable; SPEC is the first application choice for this branch.
4. Validate the final executable's ISA attributes and disassembly, vector
   instruction use, runtime/OS vector-state support, and correctness on the
   matching simulator or hardware. Compare outputs against a trusted native
   execution and verify complete job/collection status.
5. QEMU or other emulation may support functional validation and code inspection;
   its elapsed time is not a vector-hardware performance label.

Use a vectorization-disabled build on the *same vector-capable target* as a
diagnostic control if useful. Also retain the original compiler's normal
vector-capable build as the compiler-performance baseline. Keep these questions
distinct: whether vectorization helps, whether the compiler cost model helps,
and whether a cost-model change improves performance.

**Gate:** no tuning search until vector code generation is demonstrated in the
real application's relevant hot code and the baseline application completes
correctly on the selected target.

## Phase 2: define a Rocket-vector cost model

1. Audit the pinned compiler backend and target description to determine which
   vector costs are actually consulted for the selected implementation.
   Separate instruction costs, vector-length and element-width effects,
   memory/alignment or masking behavior, register pressure, and scheduling
   assumptions only where the compiler exposes corresponding model inputs.
2. Do not apply scalar `rocket_tune_info` edits to a vector model by assumption.
   The scalar cost-table mechanism may be reused only for fields proven to
   influence the selected vector target. If vector scheduling or another
   backend structure must change, isolate it as a new, bounded model dimension
   with its own tests and provenance.
3. Begin with a small causal ablation: one justified vector cost dimension at a
   time, hypothesis and falsifier recorded for each proposal. Inspect generated
   code and deduplicate candidates with identical executables before spending
   target time.
4. Make candidate compiler snapshots immutable and content-addressed. Record
   source diffs, full compiler/wrapper identities, build recipe, target
   manifest, vector flags, application binary and input hashes.
5. Add focused offline tests for proposal bounds, forbidden/unrelated source
   changes, immutable snapshots, vector ISA validation, target mismatch,
   duplicate binaries, and failed or incomplete application results.

Do not treat architectural parameters or instruction costs inferred from
source as measured latencies. Do not transfer MegaBOOM's scheduling model or
measured values to Rocket.

## Phase 3: establish a target-specific measurement baseline

1. Run the same verified vector-capable application baseline repeatedly on the
   same exact RTL simulator or physical target to estimate repeatability,
   runtime, and cost per observation. Include workload, input, compiler,
   binary, runtime/rootfs, target RTL and simulator or FPGA image and driver,
   memory model, worker, cache status, and independent sample identity in each
   record. Keep simulated target cycles, host wall time and FPGA observations
   as separate metrics and datasets.
2. Freeze correctness checks, primary metric, aggregation weights, per-workload
   regression limits, a minimum practically useful effect or precision goal,
   and a pilot-derived time/candidate budget before search.
   Do not assume the scalar plan's proposed candidate counts or thresholds are
   appropriate for vector Rocket.
3. Preserve the real-application requirement. Microkernels may diagnose code
   generation or hardware behavior, but cannot substitute for application
   performance evidence.
4. Use paired baseline/candidate measurements and explicit independent repeat
   identities. Keep worker affinity and measurement protocol fixed. Never count
   a cache hit as an independent repeat.
5. Use authorized SPEC CPU2017 inputs under their license and applicable
   run/reporting rules. Preserve the handoff's train/holdout split and native
   comparison gates. If access is unavailable, document the blocker before
   choosing a public real application as a fallback.

**Gate:** if target variability, application runtime, correctness, or collection
behavior prevents a credible comparison, stop and resolve that issue before
search.

## Phase 4: bounded search and independent confirmation

1. Run a finite proposal process using only training observations and bounded,
   reviewable code features. Record all proposals, failures, duplicate
   executables, build outcomes, and measurement results.
2. Start with isolated, source-justified vector-cost changes; expand to small
   combinations only if the ablations show useful sensitivity. Compare against
   a deterministic baseline/search policy at the same measurement budget
   before claiming the adaptive method helps.
3. Select candidates using the predeclared metric and regression limits.
   Report each workload and input alongside any aggregate. Retain the original
   compiler if results do not meet the predeclared evidence threshold.
4. Freeze selection before measuring held-out workloads or inputs. Confirm
   finalists with fresh paired/order-balanced blocks and cache namespaces that
   cannot reuse exploratory measurements. Report effect size, uncertainty, and
   the limits of the sample design.
5. Compare vector Rocket only against its own baseline. A scalar Rocket or
   MegaBOOM comparison may be discussed as context, but do not pool timings or
   imply a controlled cross-target comparison unless compiler, workload,
   runtime, and measurement differences are explicitly addressed.

## Safety, ownership, and publication boundaries

- Begin with offline inspection and tests. Do not start controllers, provision
  instances, reflash/reboot workers, or modify shared-host networking as part of
  drafting or implementing this plan.
- Any later hardware run must use an explicitly approved, available worker and
  its verified matching image/driver. Do not disturb shared services or another
  experiment.
- Keep credentials, private manifests, licensed inputs, generated binaries,
  root filesystems, and raw/private logs outside Git.
- Publish sanitized code, target/compiler identities, validation evidence,
  results, and limitations. Do not claim an FPGA design hash from a generic
  driver fingerprint or present emulation timing as hardware timing.

## Planned deliverables and exit criteria

1. A recorded Saturn selection and evidence-backed feasibility report for the
   exact Rocket plus Saturn configuration.
2. A target-specific, sanitized manifest schema/example and fail-closed
   preflight with offline tests.
3. A reproducible vector-capable compiler baseline and correct real-application
   run on the selected target.
4. A bounded, tested Rocket-vector compiler model and candidate build path, or
   a documented stop decision if the compiler/backend/target does not support
   it.
5. A target-specific pilot, a finite search record, and independent held-out
   confirmation only if prior gates pass.
6. A report that distinguishes code-generation evidence, functional
   validation, hardware measurements, uncertainty, and unresolved limitations.

Selecting Saturn does not establish a verified SPEC runtime, performance
result or speedup. Each later gate still requires its own evidence.
