# Coordinated BOOM cost-model campaign

`focused_campaign.py` targets real SPEC2017 Exchange2 train execution on the two
existing, verified MegaBOOM F2 workers. It expands the compiler model beyond
scalar-table perturbations: BOOM-specific hooks independently price GPR→FP,
FP→GPR, GPR loads/stores and FP loads/stores. Combined with branch/memory costs,
these change register-allocation and spill/branch tradeoffs. The values are
experimental optimization heuristics; they do not claim measured latencies.

The original GCC/ISA/ABI, baseline flags and libraries remain fixed. Four
coordinated profiles seed different allocation regimes: integer residency,
cheap L1 spills, asymmetric transfers/reloads, and stronger branch/pressure
tradeoffs. Further complete profiles come from the authenticated Claude CLI,
conditioned on actual native-correct SPEC train results and prior train evidence.
Claude cannot submit executable patches or change flags/networking. Reference
inputs never enter its prompts. The unvalidated generic-kernel surrogate does
not rank candidates in this campaign.

One producer rebuilds immutable compiler snapshots, validates SPEC test inputs
in QEMU and native comparisons, then prepares train images. Two consumers run
on distinct physical F2s with fixed candidate-to-worker pairing and independent
paired baselines. Preparation overlaps FPGA execution. Each candidate uses one
train measurement initially. Identical application executable sets are skipped
before FPGA execution without inventing a score. Native correctness, job and
collection statuses remain mandatory for every hardware timing.

The campaign imports baseline cache records only. A sample is reused only when
the existing full runtime/input/hardware/physical-worker/repeat key matches;
raw outputs and native correctness are revalidated. Reference cache records
are only queried in the final confirmation stage. A second worker without a
matching historical baseline receives a fresh baseline measurement.

The finite budget defaults to six proposals: four seed profiles and two measured-
feedback proposals. A winner must clear the configured improvement threshold,
then pass three independent train measurements before baseline/winner reference
validation. If confirmation falls below threshold, the baseline is retained.
This is a single-application optimization experiment, not a reportable SPEC score
or a generalization claim. A positive result can justify an x264/other-program
holdout experiment with its own correctness and runtime pilot.

```bash
source /private/run/env.sh
# First prepare and validate two coordinated profiles without FPGA execution:
python -m examples.boom_cost_model.focused_campaign \
  --config /private/focused.json --run-dir /private/focused-run --prepare-only
# Start/resume the long controller in your tmux:
python -m examples.boom_cost_model.focused_campaign \
  --config /private/focused.json --run-dir /private/focused-run
```

Use `campaign_budget` (2..12), `confirm_repeats` (1..5), `final_ref`,
`min_improvement`, `baseline_cache_dirs` and the existing approved config fields.
The first version explicitly accepts only `benchmarks: ["648.exchange2_s"]`;
benchmark expansion requires a new experiment. Watch `progress.json` for active
workers, prepared proposals, paired baselines and scored history. Compiler,
SPEC build, QEMU, native validation, F2, proposal and failure artifacts stay
under the private run directory. Ctrl-C requests a drain rather than discarding
active measurements; resuming the same command revalidates saved evidence.

Do not run another FPGA controller against these two slots concurrently. The
preflight refuses an already active FireSim driver and preserves its image.

For a bounded repeatability check of a completed candidate, use
`paired_check.py`. It revalidates the saved compiler, workload archive and SPEC
test outputs, then measures baseline/candidate/candidate/baseline on one worker
and candidate/baseline/baseline/candidate on the other. Each position has a
distinct measurement key in a new private cache; no historical measurements
are imported. Resuming revalidates already collected samples. Both workers
retain their own controls, and interrupts drain current work before stopping.

```bash
python -m examples.boom_cost_model.paired_check \
  --source /private/focused-run --candidate 3 --run-dir /private/paired-check
```

This diagnostic uses train inputs only. Two samples per compiler per worker
provide an initial repeatability check, not statistical proof or reference
validation. It leaves the completed campaign's selection decision unchanged.
