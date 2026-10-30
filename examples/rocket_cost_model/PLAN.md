# Rocket scalar compiler cost-model plan

## Goal and scope

Adapt the measured compiler-tuning technique from
`handoff/compiler-cost-models-20261030` to scalar workloads on one verified
Rocket configuration. The teammate's MegaBOOM work stays independent. Share
experiment plumbing and comparable workloads, while keeping target models,
compiler snapshots, measurements and conclusions separate.

Research question: can bounded changes to GCC's scalar optimization costs and,
in a separate stage, scheduling assumptions improve correct application
execution on Rocket relative to the original compiler?

Start with existing scalar integer code. Scalar floating-point code may be a
later, separately reported workload class if supported by the selected target.
Use a fixed target-supported ISA without V, a fixed ABI, compiler revision,
optimization level, libraries and link settings. Explicitly disable loop and
SLP vectorization for both baseline and candidates. Verify final executable
ISA attributes and disassembly, including linked code. Do not assume that
`-mtune=rocket` alone establishes the hardware or ISA.

This commit records the plan. No Rocket controller or target performance result
is implemented by this document. The exact Rocket target, toolchain, available
execution backend, licensed workloads and run budget remain to be verified.

## What we reuse and what changes

| Piece | Approach |
| --- | --- |
| Bounded proposals | Reuse validated JSON proposals; add an expected code change and falsifier. No model-generated executable patches. |
| Compiler rebuild | Reuse immutable frontend snapshots and original-driver wrappers. Verify Rocket's actual baseline and source rather than inheriting BOOM's hard-coded compiler hash. |
| Correctness | Reuse independent kernel oracles and native SPEC comparison gates when SPEC is available. QEMU supplies functional checks only. |
| Measurement | Reuse complete runtime/input/compiler identities, per-worker controls, repeat keys, validated caches and explicit reuse labels. Add the Rocket target identity. |
| Search | Reuse finite seed/feedback iterations and duplicate-executable detection. Keep the learned kernel surrogate out of candidate ranking until separately validated on Rocket. |
| Hardware | Implement a separate Rocket manifest/preflight and measurement adapter. Preserve the current MegaBOOM checks and controllers. |
| Scheduling | Inspect the pinned Rocket implementation and GCC backend. Keep scheduling fixed during the initial scalar-cost search. Never import BOOM widths, ports or latencies as Rocket facts. |

Useful implementation references are `chia/chipyard/cost_model.py`,
`measurements.py`, `spec_validation.py`, and
`examples/boom_cost_model/{optimize,focused_campaign,paired_check,tasks}.py`.
The handoff's `research/HANDOFF.md` explains evidence and limitations. In
particular, historical register-parking explanations were unsupported, and
small synthetic kernels did not establish SPEC ranking accuracy.

## Iterative loop

1. **Establish a control.** Verify the Rocket target, inspect the original
   compiler identity, build with the fixed scalar flags, validate outputs and
   measure each training workload on its assigned worker. Also rebuild the
   unchanged compiler and check code generation before attributing effects to
   cost edits.
2. **Propose a bounded change.** Start with isolated scalar-cost edits. Record
   the current full table, changed field, expected code-generation effect,
   supporting evidence and a result that would falsify the hypothesis. Later
   proposals may use measured training history through the existing LLM pattern.
3. **Prepare the candidate.** Build an immutable compiler snapshot, compile the
   same workload, inspect final code and check correctness. Save failed proposals
   and diagnostics. Deduplicate identical executable sets and record aliases;
   they do not count as fresh code-generation evidence.
4. **Measure on Rocket.** Run correct, distinct candidates on the verified
   target, paired with that physical worker's baseline. Record raw target timing,
   completion/collection status and provenance. QEMU and host compile time never
   become performance labels. Infrastructure failure stops dispatch and produces
   no candidate score.
5. **Analyze and feed back.** Compare per-workload speedups and regressions,
   inspect changed hot code, and use training evidence to propose the next
   isolated change. Preserve failed hypotheses. After isolated effects are
   understood, test a small number of interactions.
6. **Confirm or retain baseline.** Counterbalance baseline/candidate order,
   run fresh independent repeats, then evaluate held-out inputs/programs after
   selection is frozen. Retain baseline if the gain is too small, correctness
   fails, or confirmation does not hold. Report negative results as progress.

Use one producer to prepare compiler/workload artifacts ahead of measurement.
Start with one target worker; add parallel consumers only if separately verified
Rocket workers are available. Preserve workload-to-worker pairing. Every
controller needs a finite proposal/time budget, a lock, atomic progress records,
resume validation and a drain-on-stop path. A manager timeout does not establish
that a detached hardware job stopped; check the slot before any retry.

## Milestones and completion gates

### 1. Verify the target and scalar baseline

Record Chipyard/Rocket revisions, exact configuration, relevant pipeline and
cache parameters, supported ISA/ABI, compiler/backend revision, baseline flags,
execution backend and runtime identity. For FPGA execution also pin the image,
matching driver, shell and physical worker. For RTL execution pin simulator
binary/configuration and invocation. Choose one backend for the first campaign;
do not pool RTL and FPGA timing labels. Target cycles or guest time must use the
same measurement protocol for baseline and candidate.

Deliverable: a private verified manifest, a sanitized manifest schema/example,
and one correct baseline run. Missing hardware facts block performance runs,
not offline implementation. Do not launch the existing MegaBOOM controllers
against Rocket.

### 2. Implement the smallest Rocket loop

Add Rocket-specific entry points under `examples/rocket_cost_model/`. Reuse or
extract shared helpers only where behavior is target-independent. Parameterize
compiler identity/build roots so Rocket snapshots cannot collide with BOOM.
Begin with cost-table edits to the pinned Rocket tune; preserve the scheduler.
Do not add directional allocation hooks or new scheduling reservations until
there is Rocket-specific evidence motivating them.

Tests should cover proposal bounds, permitted source changes, unchanged-build
code generation, target mismatch rejection, correctness/completion failures,
scalar-code validation, compiler/runtime cache separation, duplicate code,
worker/repeat pairing and interrupted-run recovery. Run offline checks before
connecting the controller to hardware.

Deliverable: one baseline and one bounded candidate traverse the complete loop,
with saved artifacts and a trustworthy success or rejection result.

### 3. Run a small scalar pilot

Use original integer kernels covering dependent arithmetic, independent chains,
constant multiply versus shift/add, branch-heavy code, streaming loads/stores,
and dependent pointer access. Vary dependency structure and working-set size;
keep initialization and correctness checking outside the timed region. Treat
probes as effective loop costs, not exact instruction latency measurements.
Inspect assembly so a changed JSON value is not mistaken for changed code.

If licensed SPEC CPU2017 and the Rocket runtime are available, pilot Exchange2
for continuity with the teammate, then admit a second application only after
correctness, runtime and hot-code inspection. The exact set is selected from
measured pilot costs; MegaBOOM's timings do not predict Rocket runtime. Reserve
one distinct workload or input for final validation before adaptive search.
Do not commit SPEC source, extracted code, inputs, binaries or raw logs.

Deliverable: baseline repeatability, per-run wall-time estimates, visible
code-generation sensitivity and an affordable training/holdout split.

### 4. Run the bounded adaptive campaign

Proposed initial budget: six distinct candidate configurations, beginning with
isolated neighborhoods of multiply, branch and memory costs around Rocket's
actual baseline. Choose numeric bounds after inspecting the pinned backend.
If isolated changes provide useful evidence, use remaining candidates for
small combinations; otherwise stop and revise the workload or search space.
A proposal LLM may consume only training history and bounded code features.
Keep held-out outcomes out of its prompts. Include a deterministic seed/diversity
comparison at the same measurement budget before claiming adaptive search helps.

Use one exploratory sample per candidate only after characterizing baseline
variability. Initial promotion threshold: 1% geometric-mean training speedup,
subject to revision from pilot repeatability before search begins. Report every
workload separately, and reject an aggregate win that violates a predeclared
per-workload regression limit. Freeze that limit and aggregation weights before
search. Track useful distinct configurations per target-hour, preparation time,
idle time and correctness/infrastructure failures.

Deliverable: complete proposal history, raw validated observations, compiler
identities, code-change summaries and an explicit selection decision.

### 5. Confirm and compare

For finalists use fresh counterbalanced ABBA/BAAB blocks where practical, with
at least three independent samples per compiler per worker and additional
sampling if variability prevents a useful conclusion. Confirmation keys must
not reuse exploratory observations. Report individual observations, effect size
and uncertainty appropriate to the measurement design. Repeated guest samples
are not independent machines. Evaluate held-out inputs/programs only after
selection and preserve a separate final report.

For the Rocket/MegaBOOM comparison, align scalar sources, input sets, ISA subset,
compiler revision/flags and search budget where practical. Document necessary
differences. Compare each target against its own original-compiler baseline;
do not interpret unlike-core absolute times or pool their training labels.
CPU2017 experiments remain research estimates unless reporting rules are met.

Deliverable: a reproducible Rocket result, including baseline-retained outcomes,
and a clearly qualified comparison with the teammate's MegaBOOM results.

## Progress and commit sequence

- [x] Create a Rocket research branch from handoff commit `fd6bff3`.
- [x] Record scope, loop, milestones and validation requirements.
- [ ] Verify Rocket hardware/backend and compiler baseline.
- [ ] Add target manifest/preflight and offline tests.
- [ ] Add scalar compiler/workload preparation and original kernels.
- [ ] Add bounded Rocket controller with measurement, resume and drain tests.
- [ ] Complete pilot and freeze workload/search/confirmation budgets.
- [ ] Run campaign, confirm finalists and publish sanitized results.

Keep each implementation milestone in a separate focused commit with validation
notes. Store site configuration, credentials, licensed artifacts and raw runs
outside the checkout. The experiment owner starts long hardware controllers in
their own tmux, following the handoff workflow. This plan does not start jobs or
provision machines.
