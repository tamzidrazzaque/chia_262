# Hardware-informed BOOM compiler experiments

## Implemented pieces

The original compiler remains GCC 13.2.0 at the pinned revision recorded in
`cost_model.py`. The experimental compiler selects `-mtune=boom` through its
immutable wrapper. `boom_model.py` adds a separate tune table and DFA scheduling
automaton, preserving Rocket. Its seeds come from MegaBOOM V3 at BOOM revision
`5223e44cfeb26f41380057a2eb4d651197475f69`: four-wide decode/retirement,
four integer issue slots, two memory slots, two FP issue slots, integer multiply
latency three, and FP FMA latency four. The scheduler uses pooled ports; this is
an approximation. Load-use, division, conversion, branch and memory assumptions
are explicitly uncalibrated. A named tune entry does not establish accuracy.
The initial source-seeded multiply heuristic of three regressed the multiply
kernel; a paired cost-only ablation restored performance at cost four. The
current default therefore uses multiply heuristic four while retaining the
three-cycle scheduling latency. The original source seed remains available as
`SOURCE_SEED_COSTS`. This kernel correction establishes no SPEC gain.

`fast_campaign.py` compiles multiple immutable compiler snapshots into one
bootable image. Original C kernels cover streaming memory, dependent pointer
loads, data-dependent branches, independent integer arithmetic, division and
exact dyadic floating-point accumulation. Python computes independent checksums.
All 18 records per variant (six kernels, three repetitions) and every exit/
collection status must pass. QEMU gates function only; its times never train
the surrogate. F2 timing uses `CLOCK_MONOTONIC`, avoiding the unsupported guest
user `rdcycle` instruction encountered in the earlier probes. Warmup, timer
overhead and guest execution are included; these are not exact instruction
latency measurements. Assembly and binary hashes are retained for diagnosis.

`analyze_screen.py` exports paired hardware observations, validates an empirical
nearest-neighbor surrogate, and compares proxy ranks with **train-only** SPEC
observations. `tuning_search.py` requires eight distinct generated executables
with correct hardware labels and greater than 60% leave-one-executable-group-out pair ranking
accuracy before exploiting predictions. Every fourth selection explores. These
are initial policy settings, not statistical guarantees. Replicates are pooled
before fitting; QEMU labels and mixed hardware/runtime targets are rejected.
Identical generated binaries are held out together and tied in transfer checks;
batch-position/cache variation is not credited as a code-generation effect.
Proxy-to-SPEC transfer is reported separately and must be investigated before
using a proxy to prune SPEC candidates.

`campaign_queue.py` prepares the next batch while the current batch runs on both
F2s. Its plan is finite, records progress, and drains on Ctrl-C. A manifest plan
contains existing compiler snapshot JSON paths; it does not autonomously call
Claude or build proposed compilers. This separates an implemented overlap of
preparation/measurement from the future adaptive proposal producer.
After cross-worker equivalence checks, `--worker` can target one configured
instance or SSH alias. Separate queues with distinct plans can partition work
across the two F2s rather than repeat every batch on both; preflight checks still
apply and an unconfigured host cannot be selected.

## Next optimization loop

1. Measure all historical proposals with the cheap screen, then evaluate which
   kernel features reproduce known SPEC regressions/improvements. Do not assume
   a synthetic-kernel win transfers to a full application.
2. Calibrate the BOOM scheduling model with dependency/throughput probes and
   compiler-sensitive kernels. Change one source-derived scheduling feature at
   a time, then evaluate joint changes. Keep the original compiler as control.
3. Build an initial diverse BOOM dataset using the source seed, issue rates
   2/3/4 and isolated branch/memory/transfer-cost neighborhoods. Save assembly
   differences as features. Deduplicate identical generated executable code
   before scheduling redundant measurements. The fast campaign now executes
   each distinct full executable only once per batch, recording explicit
   aliases and marking identical-code variants as reused rather than independent.
   Each canonical executable still gets three timed guest repetitions.
4. Use measured labels, predictive validation, diversity and uncertainty to
   rank a bounded pool. `suggest_next.py` implements this decision. Give Claude
   the evidence/validation report and changed hot code, and request a testable
   compiler hypothesis rather than an unsupported numerical guess.
   `propose_next.py` supplies measured evidence, failed/successful validation,
   the bounded pool and a programmatic recommendation to the authenticated
   Claude CLI. Its response must choose an existing pool member and include
   both a hypothesis and a falsifier. Proposal generation remains a separate
   command; the queue does not yet automatically produce compiler snapshots.
5. Promote a small number of distinct candidates to SPEC train. Check whether
   the screen predicted their directions. Feed train observations back into
   feature/benchmark selection. Reserve reference inputs for final confirmation.

Measure useful configurations per F2-hour, time spent idle, build/boot/measure
time, validation failures, and ranking accuracy. Keep a prepared queue at least
one batch ahead. If the useful queue is exhausted or validation fails, stop;
repeating known workloads solely to show utilization does not improve evidence.
The user starts the long controller in their own tmux. Existing instance, SSH,
AGFI/driver and lab network checks remain required for every hardware batch.

## SPEC selection

Select workloads by the compiler decision under study and its share of hot
execution. The matching MegaBOOM is four-wide at decode/retirement with a
128-entry ROB. Dynamic scheduling can hide some local instruction-order
differences; the compiler still determines instruction selection, spills,
branches and the available dependency graph. A changed whole executable is
insufficient evidence that a frequently executed region changed.

| Priority | Workload | Admission hypothesis and required evidence |
| --- | --- | --- |
| First existing target | Exchange2 | The existing transfer-cost edit produced a substantial train regression. Find the changed hot integer/array/recursive functions and check register moves/spills; do not assume its Fortran source implies FP arithmetic. |
| Next pilot | x264 | Test whether the compiled scalar encoder hot loops expose strength reduction, scheduling and register-pressure choices. Verify which implementations actually execute and account for every input case. |
| Conditional | Leela | Admit for branch conversion, spills or instruction selection only after a profile and assembly comparison show those choices matter in its hot search code. |
| Later broad check | GCC | Admit after identifying a hot compiler routine sensitive to the allowed edits. Compiler inlining and code-layout experiments require their own expanded search space. |
| Generalization/control | MCF | Use to test whether gains survive an irregular-memory workload. Confirm its bottleneck on this machine; dependency chains/cache misses may require other mechanisms than the current scalar costs. |

For each candidate benchmark: collect a baseline hot-function profile, inspect
generated-code changes under isolated bounded knob sweeps, and measure a short
representative replay on F2 with correctness checks. Prefer replays that preserve
live-register pressure, branch behavior and working-set size; extracting only
a tiny arithmetic expression can erase the effect we need. Licensed extracted
SPEC code remains private. Add each replay only if it distinguishes relevant
compiler settings, and retain an untouched application/input for validation.

Use whole-program impact to prioritize: if a region consumes 20% of runtime,
making that region 20% faster gives only about 3.45% overall speedup
(`1 / (0.8 + 0.2 / 1.2)`). Record the bottleneck/changed hot code before allocating
another long application run. Benchmark descriptions below provide hypotheses;
they do not replace measurements of our actual binaries.

Use `648.exchange2_s` as a quick train check because it is the shortest of the
three measured current workloads (82.10 target guest seconds at baseline).
Recorded baseline train emulation walls in `presentation-cycles.csv` were
1,720.3 seconds for Exchange2 (~28.7 minutes), 6,731 seconds for GCC (~112.2
minutes), and 6,307 seconds for Leela (~105.1 minutes), excluding setup and
collection. The historical ten-setting kernel batch took ~86 seconds of
emulation per F2; the tasks and representativeness differ substantially.
It is a Fortran integer Sudoku solver, not an FP benchmark; language alone does
not identify the instruction bottleneck. `602.gcc_s` and `641.leela_s` remain
available for confirmation after the admission checks (267.11 and 304.53 target guest seconds). Target
guest seconds do not predict host emulation wall time by themselves.

Evaluate `625.x264_s` next for a different application family; admit it only
after test-input correctness, measured host runtime, and baseline profiling.
`631.deepsjeng_s` is another search workload and may add less diversity than
x264; decide using measured profiles. Keep `605.mcf_s` as a memory-system
generalization check outside the frequent inner loop. Keep OMNeT++ excluded
until its host build issue is fixed, and multi-job XZ excluded until all cases
are correctly accounted for. Broader claims need a broader evaluated set.
The current image/ISA does not support RISC-V V vector instructions.

Use one independent SPEC train measurement during exploration, preserving
physical-worker pairing and baseline identity; reserve three independent
repeats for finalists. Reuse only already validated samples with matching
input/runtime/hardware/worker/repeat keys. Final reference inputs remain held
out, and are run after selection rather than for every rejected proposal.

## Commands

Use a private run directory and the site's existing config/environment:

```bash
source /private/run/env.sh
python -m examples.boom_cost_model.prepare_boom --config /private/config.json --run-dir /private/boom
python -m examples.boom_cost_model.fast_campaign prepare --config /private/config.json \
  --compiler /private/boom/compiler.json --run-dir /private/batch
python -m examples.boom_cost_model.fast_campaign measure --config /private/config.json \
  --batch /private/batch --run-dir /private/hardware
python -m examples.boom_cost_model.analyze_screen --screen /private/hardware \
  --prior /private/previous-spec-run --output /private/evidence.json
python -m examples.boom_cost_model.suggest_next --evidence /private/evidence.json --output /private/next.json
python -m examples.boom_cost_model.propose_next --config /private/config.json \
  --evidence /private/evidence.json --run-dir /private/claude-proposal
python -m examples.boom_cost_model.campaign_queue --config /private/config.json \
  --plan /private/manifest-batches.json --run-dir /private/queue
```

`prepare_boom --costs-json` accepts a complete validated scalar table;
`--issue-rate` accepts 1..8. A BOOM model manifest includes its source revision,
GCC diff and source hashes, assumptions and immutable frontend hashes. An
existing run directory may not be reused for a changed configuration.

## Research guiding the design

* [Learned TPU performance model](https://arxiv.org/abs/2008.01040): learn
  hardware performance and use it for tile/fusion decisions.
* [Ansor](https://arxiv.org/abs/2006.06762): combine a broad program search space,
  measured feedback, a learned model and search.
* [Halide autoscheduler](https://halide-lang.org/papers/autoscheduler2019.html):
  program/schedule features, learned prediction and tree search.
* [MegaBOOM source](https://github.com/riscv-boom/riscv-boom/blob/5223e44cfeb26f41380057a2eb4d651197475f69/src/main/scala/v3/common/config-mixins.scala).
* [SPEC Exchange2 description](https://spec.org/cpu2017/docs/benchmarks/648.exchange2_s.html).

The current implementation is an initial empirical surrogate and bounded queue,
not a reproduction of these learned systems. Publication-level conclusions
require held-out programs, random/diversity-search controls, equal measurement
budgets and confidence intervals in addition to correctness.
