# Compiler cost-model research handoff

This directory preserves the measured MegaBOOM experiments and the reusable
Chia pipeline for a collaborator starting Rocket work. Start with this file,
then `data/manifest.json`, `../USAGE.md` and `../EXPERIMENT_PLAN.md`.
The experiment owner controls launch authorization. The current owner has
explicitly authorized continuous MegaBOOM loops until stopped; a collaborator
must obtain authorization for their own cluster. Reading this handoff does not
authorize provisioning or modifying shared-host networking.

## Current result (November 5)

The follow-up data is in `data/progress-20261103.json`, alongside the older
`spec-estimates.json` covering the first two scalar searches (all ten trials)
and the coordinated/paired studies. The follow-up export includes 18 completed
campaigns, full cost/move/policy settings, 66 compiler identities and 158 saved
successful timing observations, with validated reuses explicitly labeled. Cached observations are explicitly marked and
must not be counted as additional independent measurements.

* Best confirmed Exchange2 train runtime: **76.82 s versus 82.11 s original**,
  a **6.89% speedup**, with three train confirmation keys per compared compiler.
  The first winner confirmation reuses its validated screening measurement;
  the other two are fresh measurements. Compiler identity:
  `7ea95502b6f7d87b503791ac7d1ed22385e2a6a059dc4dbf42aba867a33e16bb`.
* That same compiler passed held-out reference validation on **both F2 workers**:
  **866.27 s versus 919.62 s original**, a **6.16% speedup** (5.80% less elapsed
  time). Selected-compiler measurements are fresh; original controls are validated
  cache reuses on each physical worker. Reference results remain excluded from
  proposal feedback. One selected observation per worker is limited repeat
  evidence, not statistical significance or an official SPEC metric.
* The winner raises branch cost from 4 to 12 while preserving the earlier
  ordinary-unroll and pressure-aware scheduling/allocation settings and other
  costs. This is a combined compiler-policy result, not an isolated cache win.
  Follow-up rounds 10–17 tested larger/smaller unrolling, inlining, interactions,
  allocation/memory choices and separate compiler passes; none passed promotion.
* The independent-mechanism portfolio measured control76.82 s, multiply4 77.15 s,
  pre-allocation scheduling disabled78.94 s, tail duplication78.10 s and their
  multiply4/tail-duplication combination80.33 s. All passed correctness and
  regressed against the control. A later arithmetic round measured77.93 s
  (multiply2),77.33 s (divide24) and77.21 s (multiply2/divide3), also all correct
  and slower than76.82 s. These are screening observations, not new wins.
* An earlier compiler, `11f4c099...`, measured **889.39 s versus
  919.62 s on reference inputs**, a **3.40% speedup**. Each physical worker ran
  both compilers once, with opposite orders. This is limited repeat evidence,
  not statistical significance or an official SPEC metric. Reference results
  were excluded from proposal generation.
* Joint-cost follow-up: control 77.68 s, multiply4/branch8 78.11 s,
  multiply4/store8 78.02 s, load-cost10 77.39 s. The 0.375% screening gain failed
  the 0.5% incremental promotion rule, so the confirmed control was retained.
* Leela screening: original 304.58 s; four candidate times 328.76, 327.49,
  313.27 and 313.40 s. A later integer-idiom round measured328.76,306.58,324.21
  and307.73 s, also all correct and slower than304.58 s original.
* Planner and feedback now explicitly use **Claude Opus5.5 / xhigh** through
  the authenticated Claude CLI. Historical seeds and trials retain their real
  provenance. Structural seed ablations are not retroactively attributed to Opus.

All numerical SPEC results are **non-compliant research estimates**: partial
suite, selected train/reference inputs, FPGA simulation and custom timing.
They are not SPEC reportable scores. Licensed source, inputs, outputs, binaries,
assembly, raw logs, authentication material and site configuration are excluded.

The loop rotates experiment families, preserves the confirmed anchor, rejects
unchanged executables before FPGA work, revalidates full measurement-cache keys
and native outputs, and begins feedback after the control plus another finished
profile. See `../AUTOPILOT.md` for stop/drain behavior, explicit model policy and
staged preparation reuse. The cache investigation uses a separately
qualified workload; see `../CACHE_STUDY.md` and `data/cache-pressure.json`.
The first capacity diagnostic failed on FPGA because its smallest stream case
was shorter than the guest timer resolution. The corrected batched-clock version
passed all 48 checks on one F2. It shows a capacity transition near the 32 KiB L1;
cache, TLB and memory-parallelism effects are not isolated. No cache-oriented
compiler speedup is claimed.
Optional diagnostic failures can now be explicitly quarantined so ordinary
experiments continue through their full checks.

The next portfolio tests three different decisions: integer multiply
profitability, scheduling before register allocation, and tail duplication.
Each treatment inherits the latest confirmed anchor and changes one decision;
one feedback slot follows all three measured ablations. These extend the BOOM
compiler policy beyond scalar costs. See `../MECHANISTIC_TESTS.md` for expected
code changes, counterevidence and validation requirements. Preparation alone
does not establish a performance result.

## Historical result through October 30

The original paired check reproduced 82.11 versus81.79 s on both workers,
about0.39% train speedup, below its1% threshold. The older dataset and static
analysis remain useful evidence about why generic microkernel rankings and
small isolated scalar cost changes were insufficient. Later confirmed gains
above supersede that historical status.

## What has been tried

| Campaign | Benchmarks | Proposals | Best initial train speedup |
| --- | --- | ---: | ---: |
| Scalar 1 | MCF, Exchange2 | 5 | 1.000323× aggregate |
| Scalar 2 | GCC, Leela, Exchange2 | 4 | 0.999638× aggregate |
| Coordinated BOOM | Exchange2 | 6 | 1.003912× |

All measurements involving SPEC CPU2017 in this handoff are **estimates from
non-compliant research runs**, not official SPEC metrics: partial suites,
train inputs for search, simulated FPGA target, custom timing/collection,
and research compiler changes. Selected reference observations are labeled
separately. This handoff concerns the retired CPU2017 suite; consult the
[SPEC CPU2017 page](https://www.spec.org/cpu2017/) and
[run/reporting rules](https://www.spec.org/cpu2017/Docs/runrules.html) before
further publication. No full-suite SPEC score is claimed.

`data/spec-estimates.json` contains every successfully recorded simulation/native
comparison observation selected by the exporter, the complete cost choices for
all 15 proposals, compiler identities, input sizes, worker/repeat labels,
cache status and evidence hashes. Cached copies lacking their own simulation
completion record are not presented as fresh measurements. Observations without
legacy cache metadata are explicitly marked; source-artifact identifiers are
relative to each campaign, not local absolute paths.
`data/compiler-models.json` also retains the measured microkernel compiler
models and scheduling/move-profile identities; driver paths and binaries are
excluded.

`data/fast-kernels.json` contains timings/checksums for six original kernels,
three repetitions, two workers and four batches. Compiler/source/ELF hashes
are retained. Ten historical configurations generated only three distinct
kernel binaries; treat identical ELFs as one code-generation group. This
screen failed to establish reliable ranking of SPEC candidates and must not
be used as a trained predictor of Rocket or SPEC performance.

## New evidence and next hypotheses

Separate instrumented RISC-V/QEMU **train** profiles passed native correctness
for original GCC and candidate 3. GCC coverage reports about 34,934,090
`digits_2` function executions in each, with identical reported function counts.
Execution frequency is not a cycle profile. Instrumentation can change
optimization/allocation, and QEMU time is excluded from performance labels.
`data/coverage-counts.json` exports function/block counts, not source lines or
gcov program artifacts.

No application GPR↔FP moves were emitted by original GCC, any of the six
coordinated candidates, or the earlier FMV=4 regression. Their whole-executable
move counts occur in linked runtime code. Earlier explanations attributing
that regression to emitted integer/FP register parking are unsupported.
Compiler costs can still affect other allocation decisions indirectly.
The solver is primarily integer, while compiled `MAIN__` also contains some
floating load/subtraction/conversion operations. Avoid claiming there is no
floating-point code anywhere in the application.

Candidate 3 reduces static stack-relative loads 5,067→4,899 and stores
4,120→4,045 across the 27 application symbols. Saves/restores are included;
these are not exact spills or dynamically weighted counts. IRA estimates high
GPR pressure: `new_solver` 137→136, `rearrange` 131→131, `digits_2.isra.0`
115→105. Allocator "Spilling" log-line counts include retries and are not
executed spill counts. Pressure-aware scheduling, live-range choices and
unrolling are better-motivated next experiments; later follow-up campaigns tested these interventions on hardware (see above). Use hot-block evidence and small causal ablations
before expanding a search or making a latency/port-bottleneck claim.

## Reuse for Rocket

* `chia/chipyard/cost_model.py` preserves original GCC and builds immutable
  snapshots; its original path edits `rocket_tune_info`. Compiler identity,
  source revision, wrapper/frontend hashes and actual worker prefix are part
  of the workload identity. Changing a JSON label alone cannot select a compiler.
* `boom_model.py` adds an independent BOOM tune/scheduler and bounded directional
  move/spill costs. It does not replace Rocket. Its pooled issue resources and
  several latencies are approximations, not measured hardware facts.
* `spec_sw_build_loop.py` supports compiler-worker affinity, subsets, diagnostic
  collection and input/compiler-aware image identities. The compiler worker
  needs a licensed writable SPEC installation mounted at `SPEC_DIR_2017`.
* `spec_validation.py` checks guest/job/collection statuses and native SPEC
  comparisons. `measurements.py` keys timings by full software/runtime,
  input size, hardware, physical worker and independent repeat; never pool
  Rocket and BOOM labels or treat cache hits as additional independent samples.
* `fast_kernels.c`, `latency_probe.c`, batch preparation, opcode feature extraction
  and executable-group validation can be reused with a separately verified target.
* Existing `optimize.py`, `focused_campaign.py`, `paired_check.py` and their
  hardware preflight are deliberately restricted to the verified MegaBOOM image.
  **They are not ready-to-run Rocket controllers.** Implement and test a
  Rocket-specific manifest/preflight that checks its own AGFI, driver, revisions,
  shell and worker identity. Keep the current MegaBOOM checks intact. A Rocket
  compiler cost table does not turn a MegaBOOM image into Rocket hardware.

`data/provenance.json` pins the exact compiler/hardware/Speckle facts. The data
target is the public FRFCFS/LLC MegaBOOM image, distinct from the unavailable
intended FCFS16 variant. Preserve rv64imafdc/lp64d and the baseline flags when
making comparable compiler experiments. The current ISA/image does not provide
RISC-V V instructions. A new Rocket target requires its own baseline and a
fresh proxy-to-application validation.

## Setup and useful entry points

Run offline software checks before accessing a worker:

```bash
python -m pytest -q \
  chia/chipyard/test/test_cost_model_loop.py \
  chia/chipyard/test/test_boom_model.py \
  chia/chipyard/test/test_boom_move_profile.py \
  chia/chipyard/test/test_fast_screen.py \
  chia/chipyard/test/test_tuning_search.py \
  examples/boom_cost_model/tests
```

Use the existing site cluster, authenticated Ray token file, loopback listener
guard, trusted SSH aliases/tunnels and approved AWS restrictions. Keep generated
cluster JSON/YAML, credentials and hardware driver bundles outside the checkout.
`config.example.json` shows the fields using placeholders. It is a MegaBOOM
template, not a runnable site configuration or an adapted Rocket controller;
the approved network policy must be filled from the site's existing policy.
`examples/firesim_spec/prepare_cluster.py` and `stage_existing_f2.py` are
preparation helpers with generic example defaults; review explicit paths and
required environment variables before the owner runs them. They do not replace
the site's policy. Do not reboot/reflash an occupied FPGA or stop other users'
services. User-specific lab setup notes and administrator installer scripts
are intentionally not part of the public handoff.

For the existing MegaBOOM pipeline, the owner can prepare/launch following
`USAGE.md`, `FOCUSED_CAMPAIGN.md`, `prepare_gcc.py`, `prepare_boom.py`,
`fast_campaign.py`, `focused_campaign.py` and `paired_check.py`. Only use a
verified matching image/driver. The preparation and measurement commands in
those guides are actions for the experiment owner; this handoff starts none.

To regenerate the numerical dataset from an authorized local archive:

```bash
python -m examples.boom_cost_model.export_research \
  --run-root /private/run \
  --compiler-build-root /private/compiler-builds \
  --output examples/boom_cost_model/research/data
```

The exporter reads a fixed artifact allowlist and checks saved native/simulation
success. It is not a new SPEC execution or a fresh native revalidation of every
historical run. Data hashes in `manifest.json` and offline export tests detect
accidental changes. The private raw archive is still required for a full
correctness audit or reanalysis at source/instruction granularity.

## Sharing boundary and open issues

Included: project-authored code, original microkernels, tests, numeric cost
choices, elapsed-time estimates, checksums/hashes, sanitized function/block and
allocation summaries, revision identities and reproducibility notes.

Excluded: SPEC ISO/installation/source, benchmark inputs/reference outputs,
executables/root filesystems, SPEC assembly/IR, gcov notes/data containing program
structure, raw console/compiler/Claude logs, private site configuration and
credentials. Authorized collaborators need their own licensed installation and
local permission to inspect the private archive; git access does not grant that.

Known limitations/failures: the first MCF reference manager timed out while its
detached driver kept running; manager timeout alone must never justify relaunching
into that slot. Earlier startup and result-collection failures are preserved in
private logs. QEMU user `rdcycle` was unavailable, so original probes use the
monotonic guest clock. The installed QEMU lacks plugin support; the successful
coverage profiles instead used compiler instrumentation. One earlier SPEC
omnetpp build failed at C++ compilation, before hardware execution. The full
SPEC suite is not validated. The learned kernel surrogate remains untrusted.
Do not advertise a substantial compiler improvement or a trained performance
model from the current data.

Other remote branches (`boom-cost-model-experiments`,
`research/spec2017-cost-model`) contain separate work. This handoff preserves
them and current main; inspect overlaps before merging or cherry-picking.
