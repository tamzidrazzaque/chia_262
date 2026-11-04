# Rocket scalar compiler cost-model plan

> **Vector-campaign note:** This file is the inherited scalar Rocket reference.
> The active Rocket plus Saturn campaign, including the five experiment roles
> and the separate roles 1-3 compiler loop and roles 4-5 private-source loop,
> is defined in [VECTOR_PLAN.md](VECTOR_PLAN.md). Do not use this scalar plan as
> the vector experiment specification.

## Goal and scope

Adapt the measured compiler-tuning technique from
`handoff/compiler-cost-models-20261030` to scalar workloads on one verified
Rocket configuration. The teammate's MegaBOOM work stays independent. Share
experiment plumbing and comparable workloads, while keeping target models,
compiler snapshots, measurements and conclusions separate.

Research question: can bounded changes to GCC's scalar optimization costs and,
in a separate stage, scheduling assumptions improve correct application
execution on Rocket relative to the original compiler?

Start with real scalar integer applications, using the handoff's SPEC/FireSim
application path. Synthetic kernel campaigns are outside our initial scope.
Offline helper tests remain useful for implementation correctness.

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
matching driver, shell and physical worker. The initial campaign uses F2 execution. Choose one verified target for the campaign;
do not pool RTL and FPGA timing labels. Target cycles or guest time must use the
same measurement protocol for baseline and candidate.

Deliverable: a private verified manifest, a sanitized manifest schema/example,
and one correct application baseline run. Missing hardware facts block performance runs,
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

### 3. Run a real-application pilot

Use an existing verified Rocket F2 image and matching driver, then run real
application test inputs before training inputs. Prefer the public single-core
candidate in `IMAGE_DISCOVERY.md`, subject to completing driver/source checks.
Do not add a synthetic-kernel or bare-metal RTL campaign as a prerequisite.
Measure baseline variability and inspect hot application code and compiler
changes directly. Keep the compiler/ISA/ABI and workload runtime fixed.

If licensed SPEC CPU2017 and the Rocket runtime are available, pilot Exchange2
for continuity with the teammate, then admit a second application only after
correctness, runtime and hot-code inspection. The exact set is selected from
measured pilot costs; MegaBOOM's timings do not predict Rocket runtime. Reserve
one distinct workload or input for final validation before adaptive search.
Do not commit SPEC source, extracted code, inputs, binaries or raw logs.

Deliverable: baseline repeatability, per-run wall-time estimates, visible
code-generation sensitivity and an affordable training/holdout split.

### 4. Run the bounded adaptive campaign

Proposed initial budget: up to six distinct candidate configurations, with a
hard cap of twelve proposal attempts and a pilot-derived wall-time budget.
Duplicate or invalid proposals consume attempts; stop at the first exhausted
budget rather than searching indefinitely for six distinct binaries. Begin with
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

For finalists use two fresh ABBA/BAAB blocks per worker, giving four independent
samples per compiler per worker, and additional
sampling if variability prevents a useful conclusion. Confirmation keys must
not reuse exploratory observations: include a campaign phase and independent
block/sample identifier, or use an isolated confirmation cache namespace.
Repeat index alone is insufficient because the inherited cache can otherwise
reuse a search sample as confirmation. Report individual observations, effect size
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

## Feasibility check and runtime budget

Scope update: real applications on an existing Rocket F2 image are the first
measurement path. The earlier host-kernel checks below are historical software
checks, not a proposed experimental stage. See `IMAGE_DISCOVERY.md` for the
public image found after this initial feasibility check.

Checked locally on 2026-10-30:

- The installed Chipyard toolchain supplies GCC 13.2.0 for RISC-V Linux and
  bare-metal targets. The Linux compiler accepts Rocket tuning and explicit
  `-fno-tree-loop-vectorize -fno-tree-slp-vectorize` flags. The reference kernel
  harness cross-compiled to assembly with an ISA attribute containing no V.
  Final linked executable/library validation remains part of implementation.
- The inherited six-kernel host harness passed all 18 checksum/timing-format
  checks in about 0.24 seconds including native compilation. This checks
  functionality only; it estimates neither Rocket speed nor RTL wall time.
  It includes scalar floating point; select integer kernels for the first pilot.
- Shared speedup calculation accepted a correct comparison and rejected zero
  times and mismatched workload sets. This is a small helper smoke check,
  not end-to-end controller validation.
- Local Chipyard includes a single-core `RocketConfig`, but the two existing
  simulator executables are tethered multi-chip configurations. Neither is
  accepted as the campaign target without manifest/build verification.
- The Chipyard Python environment has pytest but lacks Ray/MCP and has
  Pydantic 1.x. It cannot run the handoff controller unchanged. Create an isolated
  compatible CHIA environment; do not alter the shared Chipyard environment.
- Compiler rebuild helpers pin a specific baseline hash/source and Linux
  target. Bare-metal work needs its own verified rebuild recipe, startup and
  libraries. Parameterizing an experiment label alone is insufficient.

The method is feasible, but the Rocket controller, verified execution target,
compiler rebuild and environment are unfinished. No target timing has yet been
measured here. The estimates below are planning allowances, not observed
Rocket runtimes or deadlines.

| Stage | Initial allowance | What determines it |
| --- | --- | --- |
| Environment, matching Rocket driver and F2 target verification | Budget after driver provenance check | Existing image is available; driver/build compatibility remains unverified |
| Initial reproducible GCC rebuild | Several hours; allow a day for setup/debugging | Host resources, baseline recipe and source availability |
| Rocket application controller adaptation and tests | Two to five working days | FireSim/SPEC integration, target-specific checks and recovery paths |
| SPEC campaign | Budget only after a Rocket FPGA pilot | Verified image/driver, per-input runtime, build cost and available workers |

For one worker, let B be the wall time to execute and collect the entire training
workload set once, P the corresponding held-out workload-set time, G the
incremental compiler rebuild time per candidate, and W the workload build and
functional-validation time per candidate. With three initial baseline samples,
six distinct candidate samples, four fresh baseline and four fresh winner
confirmation samples, the target-only upper allowance is **17 B + 8 P** for
one finalist and four held-out samples per compiler. Without a promoted finalist,
stop after the search: **9 B**, plus preparation. Multiple finalists or a
separate equal-budget search comparison add their own explicit budget.

For example, assuming B = 10 minutes and P = 30 minutes gives about 6 hours
50 minutes of target execution; B = 30 minutes and P = 2 hours gives about
24 hours 30 minutes. These are hypothetical inputs, not measurements. Add
baseline preparation and up to six lots of G + W, proposal latency, boot/setup
costs not already counted, and failed attempts. Preparation can overlap target
execution, but adaptive proposals cannot all be prepared before feedback arrives.
A conservative estimate sums preparation and execution; ideal overlap is only
a lower bound. Include every attempt's preparation cost, even if code duplicates
an earlier candidate. Add recovery slack, not unbounded automatic retries.

Before a full campaign, time the unchanged rebuild and two candidate rebuilds,
then run three baseline target samples and one candidate end to end. Record
compile, validation, boot, target, collection and total wall time separately.
Freeze a maximum wall-time budget from these measurements. Stop dispatching
new work when that budget expires, then drain the active measurement. Never
substitute MegaBOOM's documented guest seconds for Rocket host wall time.

## Progress and commit sequence

- [x] Create a Rocket research branch from handoff commit `fd6bff3`.
- [x] Record scope, loop, milestones and validation requirements.
- [ ] Verify Rocket hardware/backend and compiler baseline.
- [x] Add target acceptance helpers and offline rejection tests.
- [ ] Complete worker preflight and verify the matching driver/build evidence.
- [ ] Add scalar compiler and real-application workload preparation.
- [ ] Add bounded Rocket controller with measurement, resume and drain tests.
- [ ] Complete pilot and freeze workload/search/confirmation budgets.
- [ ] Run campaign, confirm finalists and publish sanitized results.

Keep each implementation milestone in a separate focused commit with validation
notes. Store site configuration, credentials, licensed artifacts and raw runs
outside the checkout. The experiment owner starts long hardware controllers in
their own tmux, following the handoff workflow. This plan does not start jobs or
provision machines.

Current implementation and execution blockers are tracked in `READINESS.md`.
