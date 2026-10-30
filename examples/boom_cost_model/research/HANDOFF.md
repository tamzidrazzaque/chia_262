# Compiler cost-model research handoff

This directory preserves the measured MegaBOOM experiments and the reusable
Chia pipeline for a collaborator starting Rocket work. Start with this file,
then `data/manifest.json`, `../USAGE.md` and `../EXPERIMENT_PLAN.md`.
**The experiment owner always launches/resumes controllers in their own tmux.**
Do not start controllers, provision instances or modify shared-host networking
as part of reading, testing or setting up this handoff.

## Current result

The October 29–30 order-balanced check completed correctly on both F2s. Each
worker measured original GCC twice and coordinated candidate 3 twice:

| Compiler | Worker 0 samples (guest seconds) | Worker 1 samples |
| --- | --- | --- |
| Original | 82.11, 82.11 | 82.11, 82.11 |
| Candidate 3 | 81.79, 81.79 | 81.79, 81.79 |

The observed Exchange2 **train** speedup is 1.00391246×, approximately 0.39%.
It repeats at the timer's 0.01-second resolution on both workers. This is a
small measured gain on one input set, not a substantial optimization or a
reference/generalization result. It remains below the campaign's 1% selection
threshold. Two samples per compiler per worker do not establish a statistical
confidence interval. The completed campaign retains the original compiler.

All eight paired runs passed native SPEC output comparison, simulation
completion and collection statuses. The first scalar campaign completed its
five-candidate train search but its original reference phase timed out; it is
not marked complete. The second scalar campaign and the coordinated campaign
completed. The paired check is a separate diagnostic, not a fourth adaptive
search. Raw benchmark timing observations number 75; original-kernel timing
observations number 648. Cache/worker/repetition fields remain explicit.

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
unrolling are better-motivated next experiments; no such new model has yet
been validated on hardware. Use hot-block evidence and small causal ablations
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
