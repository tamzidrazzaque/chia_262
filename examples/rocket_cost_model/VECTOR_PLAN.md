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

## Definitive experiment structure: five roles and two loops

The campaign has five experiment roles. Roles 1, 2, and 4 are frozen reference
points. Roles 3 and 5 are iterative candidate families, not single builds.

| Role | Source | Compiler behavior | Hardware | Lifecycle |
| --- | --- | --- | --- | --- |
| **1. Scalar reference** | Unchanged licensed SPEC source | Fixed scalar build, `rv64gc`, with loop and SLP vectorization disabled | Scalar Rocket | Build, validate, and measure once as the application-level reference. |
| **2. Generic automatic-vectorization baseline** | The same unchanged licensed SPEC source | Pinned stock GCC RVV vectorizer and its unmodified cost model | Fixed Rocket plus Saturn | Build, validate, and measure once; freeze its compiler, flags, binary, and measurement identity. |
| **3. Saturn-aware automatic-vectorization candidates** | Bit-identical source and inputs from role 2 | Successive bounded changes to only the vector cost model or a separately declared vector scheduling dimension | The same Rocket plus Saturn target as role 2 | Iterate as `3.1`, `3.2`, and so on; compare primarily with role 2. |
| **4. Basic source-vectorization baseline** | A private, straightforward vector derivative made through SPEC's alternate-source workflow | Fixed compiler and flags; direct, non-Saturn-specific vector implementation | The same Rocket plus Saturn target | Create, validate, and measure once; freeze it before source optimization. |
| **5. Saturn-aware source-optimization candidates** | Successive private descendants of role 4 | The same fixed compiler configuration used for role 4 | The same Rocket plus Saturn target | Iterate as `5.1`, `5.2`, and so on; compare primarily with role 4. |

The fixed ISA strings in the table express the intended distinction. Record
the complete extension strings actually supported by the selected compiler,
runtime, and Saturn RTL rather than treating these abbreviations as manifests.

### Loop A: unchanged-source compiler-cost optimization (roles 1-3)

Role 1 establishes the conventional scalar application reference. Role 2
establishes what an unchanged application obtains from the stock compiler's
automatic RVV vectorization. Run both once and retain them as immutable
baselines. The repeated loop changes role 3 only:

```text
frozen unchanged SPEC source and inputs
                 |
       propose one bounded cost edit
                 |
       build an immutable compiler
                 |
       compile and inspect final ELF
                 |
       validate identical SPEC output
                 |
       measure on the fixed Saturn RTL
                 |
       score against frozen role 2
                 +----> next role 3 candidate
```

The controlled variable is the compiler model. Source, application inputs,
libraries, optimization level, target hardware, runtime, and measurement
protocol remain fixed between roles 2 and 3. A useful candidate may vectorize
a previously scalar loop, reject a harmful vectorization, or choose better RVV
code for a loop that was already vectorized. Do not equate "more vector
instructions" with success; correct target cycles and declared regression
limits determine the result. Role 1 supplies context for total vector benefit,
but the causal cost-model comparison is role 3 versus role 2.

### Loop B: private source-vector optimization (roles 4-5)

Role 4 is a one-time, deliberately plain vector conversion of the selected
SPEC application or hot kernel. Preserve the algorithm, inputs, observable
behavior, and SPEC output validator. Prefer vector-length-agnostic RVV code and
straightforward strip mining; do not include Saturn-specific layout, LMUL,
unrolling, scheduling, or other tuning in this baseline. Freeze its source,
compiler, binary, validation record, and target measurements.

Role 5 is a separate iterative loop that improves role 4's implementation:

```text
frozen role 4 vector source and validation
                 |
       propose one source-level change
                 |
       create a versioned private derivative
                 |
       compile with role 4's fixed compiler
                 |
       validate identical SPEC output
                 |
       measure on the fixed Saturn RTL
                 |
       score against frozen role 4
                 +----> next role 5 candidate
```

Candidate dimensions may include data layout, strip mining, LMUL, unrolling,
loop fusion, reduction structure, masking and tail handling, memory access, and
instruction scheduling, but each proposal needs a stated hypothesis and
falsifier. The controlled variable is the private application implementation;
the compiler model must not also change within this loop. An explicit-intrinsic
implementation tests programmer/source optimization and largely bypasses the
compiler's vectorization-profitability decision, so it must not be credited as
a role 3 cost-model improvement.

After both loops finish, compare the best confirmed role 3 candidate with the
best confirmed role 5 candidate to estimate the remaining compiler-to-expert
gap. This cross-loop comparison is descriptive because the source differs. It
does not replace the controlled role 3-versus-2 and role 5-versus-4 comparisons.

### CHIA execution model for the two loops

Implement the loops as separate CHIA graphs or as one graph with explicitly
separate namespaces. Baseline nodes for roles 1, 2, and 4 run once and produce
immutable, content-addressed artifacts. Candidate nodes for roles 3 and 5 may
reuse only their own matching baseline and must not share scores or cache keys
across compiler, source, target, input, or measurement identities.

Both loops use the same high-level gates: build, static ISA/vector audit, QEMU
functional check, SPEC output validation, exact-target execution, measurement
collection, and bounded scoring. QEMU establishes function only; its elapsed
time is never a Saturn performance result. CHIA should retain failed builds,
validation failures, duplicate binaries, negative results, and rejected
hypotheses instead of silently dropping them.

The first roles 1-3 preparation run completed on 2026-11-04 for unchanged
SPEC CPU2017 `648.exchange2_s` test input. All three roles passed SPEC
validation, and candidate 3.1 produced a different RVV ELF from role 2. This
qualifies the build, validation, audit, and compiler-sensitivity stages only.
The exact-target measurement and scoring stages remain open; see
[the sanitized status](ROLE_123_STATUS.md).

### Status of the private vector SPEC derivative

SPEC CPU2017 does not provide an official "vector SPEC" edition. Roles 4 and 5
are private vectorized derivatives of a licensed SPEC application. SPEC does,
however, provide an official alternate-source mechanism, the `src.alt` config
option, and the `makesrcalt` development utility. Use that mechanism rather
than patching an anonymous build directory or replacing the installed original
source. Keep a private README, parent identity, complete change manifest, and
hashes for every role 4/5 version.

Using SPEC's mechanism does not make a custom Saturn derivative SPEC-approved.
The installed CPU2017 documentation states that SPEC must approve a `src.alt`
before results using it are published under the run rules. Therefore:

- Keep licensed original source, modified source, patches, generated binaries,
  inputs, and raw outputs in the authorized private SPEC environment, not Git.
- Do not redistribute the derivative or its source-level patch without license
  authorization.
- Do not call role 4 or 5 an official or reportable SPEC result. Label it
  **"private vectorized derivative of SPEC CPU2017 `648.exchange2_s`; not an
  official reportable SPEC result."**
- Retain the original SPEC inputs and output validator and require successful
  validation for every candidate. A driver is acceptable only when integrated
  through the recorded alternate-source build and when it performs the real
  computation without bypassing validation.
- Obtain SPEC approval and human/license review before publishing modified-
  source performance results as SPEC results.

The relevant installed references are `Docs/config.html` (`src.alt`) and
`Docs/utility.html` (`makesrcalt` and src.alt development). The public listing
for SPEC-approved alternatives is <https://www.spec.org/cpu2017/src.alt/>.
Sanitized repository metadata may record hashes, compiler/target identities,
validation status, aggregate measurements, and limitations, but no licensed
source content.

## Audit result and immediate handoff

The existing plan remains the research plan. An independent artifact and
compiler audit identified the following gates for the next agents:

| Claim | Current evidence | Decision |
| --- | --- | --- |
| Saturn instruction execution | The retained ELF, simulator and log hashes match their manifest; a self-checking RVV+Zvbb test passes on `SingleHartSaturnSmokeConfig`. | Accept only for the tested bare-metal instructions and test boot path. |
| Historical Saturn probe | `MINV128D64RocketConfig` elaborated and its FIRRTL contains Saturn modules; the passing simulator uses a second config that overrides the boot ROM. | Retain as feasibility evidence only; it is not the active measurement target. |
| Active Saturn target | The official pinned catalog provides `FireSimREFV256D128RocketConfig`, AGFI `agfi-012e92467d7d2149a`, its F2 recipe and source revisions. It publishes no `driver_tar`. | Query and match the AGFI metadata, then build and fingerprint the target-specific driver from the pinned source before accepting measurements. |
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
2. **Qualify the selected Saturn target.** Use upstream
   `REFV256D128RocketConfig` (VLEN 256, DLEN 128) and its
   `FireSimREFV256D128RocketConfig` wrapper. Use the recorded official AGFI
   and source pins, then record the matching built driver, bridge metadata,
   memory/platform configuration and worker identity. The earlier MINV128D64
   instruction pass is historical feasibility evidence, not evidence for this
   target. Report a blocker if the released artifacts cannot be verified; do
   not silently fall back to scalar Rocket, MegaBOOM or another vector config.
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

**Selected implementation (updated 2026-11-04):** Saturn attached to one Rocket
core using upstream `REFV256D128RocketConfig`, with VLEN 256 and DLEN 128. The
measurement wrapper is `FireSimREFV256D128RocketConfig`. This deliberately
replaces the earlier MINV128D64 probe so the campaign can use the configuration
that upstream supports in FireSim. The official AGFI, recipe and source pins
are recorded in `SATURN_FIRESIM.md`. The locally built driver and AWS image metadata,
platform/memory configuration, Linux, SPEC and timing still must pass their
acceptance gates.

The installed Chipyard container also contains another Rocket-integrated RVV
configuration:

- Ara wrapper `V4096Ara2LaneRocketConfig`, with a 4096-bit vector length and
  two Ara lanes. Ara is documented here for provenance and is outside the
  active experiment.

The checked-in scalar Rocket image does not contain Saturn. The installed
container's older MINV128D64 evidence and revisions remain separate historical
evidence and cannot identify the active upstream FireSim target. The active
target's release revisions, AGFI and driver must be recorded from the matching
upstream artifact rather than inferred from that container. Exact historical
evidence and remaining gaps are recorded in
[the feasibility report](VECTOR_FEASIBILITY.md).

Saturn remains the chosen direction. The upstream REF configuration and FireSim
wrapper now determine the measurement target; the bare-metal MINV test only
establishes earlier Saturn feasibility. Chipyard's
[Saturn documentation](https://chipyard.readthedocs.io/en/stable/generators/saturn/)
describes virtual-memory and precise-trap support, which the existing Linux
SPEC path needs. Chipyard's
[Ara integration documentation](https://chipyard.readthedocs.io/en/stable/generators/ara/)
describes limitations in those features. These documentation claims must be
checked against the exact pinned Saturn design and guest; the current smoke
does not prove Linux application support. The source review did not establish
a Rocket+Hwacha integration in the pinned tree.

Bind all compiler, manifest and measurement identities to
`REFV256D128RocketConfig` and its exact FireSim artifact. The pinned GCC accepts
only `scalable` or `zvl` for `-mrvv-vector-bits`, not a fixed value of 256, so
the compiler path remains vector-length agnostic while QEMU correctness uses
VLEN 256. Any later parameter change creates a new target and baseline.

Do not treat `-march=rv64gcv`, a compiler flag, or a configuration name as
proof that matching hardware and software exist. If Saturn cannot be built and
executed with a verified software stack, stop at documented offline feasibility
and report the blocker. Never label the existing scalar Rocket image as
vector-capable.

## Phase 0: establish target feasibility

1. Verify upstream `REFV256D128RocketConfig` and
   `FireSimREFV256D128RocketConfig`. Record their release revisions, vector
   parameters, supported extensions, virtual-memory/trap behavior and Linux
   runtime support from source and executable checks. Do not transfer the
   installed MINV128D64 probe's executable claims to this target.
2. Use the discovered official F2 target and AGFI recorded in
   `saturn-firesim-discovery.json`. In an AWS-authenticated manager, verify its
   image description and build the exact driver from the pinned source. Record
   its configuration, ISA/extension, vector parameters (such as VLEN/ELEN when
   applicable), memory/platform settings, exact simulator RTL/binary and boot
   inputs, or FPGA image and driver/build provenance, and execution-worker identity.
   Distinguish source-derived facts from verified build facts and measured facts.
3. Check whether the image and locally built driver are compatible with the
   execution environment. The catalog does not publish a `driver_tar`; this is
   an explicit build-and-verify step, not a missing hardware-image search. Do
   not assume the public scalar Rocket F2 image or MegaBOOM driver is reusable.
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
   executable for the selected vector target. First establish roles 1 and 2
   from the unchanged source. Separately create role 4 through the private
   `src.alt` workflow and freeze it before any role 5 optimization. Inspect the
   baseline hot code for both source lines.
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

1. Run two finite proposal processes using only training observations and
   bounded, reviewable changes. Loop A proposes role 3 compiler-model changes
   against frozen role 2. Loop B proposes role 5 private-source changes against
   frozen role 4. Never change compiler and application source in the same
   candidate. Record all proposals, failures, duplicate executables, build
   outcomes, and measurement results in separate namespaces.
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
- Keep all licensed SPEC source and all role 4/5 modified source or source-level
  patches outside Git. Use the private `src.alt` workflow, preserve validation,
  and seek SPEC approval before publication under the run rules.
- Publish sanitized code, target/compiler identities, validation evidence,
  results, and limitations. Do not claim an FPGA design hash from a generic
  driver fingerprint or present emulation timing as hardware timing. Never
  describe the custom role 4/5 derivative as an official vector SPEC suite.

## Planned deliverables and exit criteria

1. A recorded Saturn selection and evidence-backed feasibility report for the
   exact Rocket plus Saturn configuration.
2. A target-specific, sanitized manifest schema/example and fail-closed
   preflight with offline tests.
3. Frozen, reproducible role 1 and role 2 baselines plus a correct unchanged-
   source application run on the selected target.
4. A private, validated, frozen role 4 `src.alt` baseline with its licensed
   contents outside Git and only sanitized provenance in the repository.
5. A bounded, tested role 3 Rocket-vector compiler-model loop and candidate
   build path, or a documented stop decision if the compiler/backend/target
   does not support it.
6. A separate bounded role 5 source-optimization loop, with the compiler fixed
   to role 4's configuration and every candidate validated against the original
   application behavior.
7. A target-specific pilot, finite search records, and independent held-out
   confirmation only if prior gates pass.
8. A report that distinguishes roles 1-5, controlled within-loop comparisons,
   descriptive cross-loop comparisons, code-generation evidence, functional
   validation, hardware measurements, uncertainty, licensing, and unresolved
   limitations.

Selecting Saturn does not establish a verified SPEC runtime, performance
result or speedup. Each later gate still requires its own evidence.
