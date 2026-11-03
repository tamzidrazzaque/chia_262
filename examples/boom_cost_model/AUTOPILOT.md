# Continuous BOOM experiments

Run this supervisor only with explicit authorization for continuing FPGA jobs.
It waits for an existing controller to release its lock and produce a completed
result. It reviews train results, pins a confirmed incumbent for each benchmark,
and asks the authenticated Claude CLI for three new controlled experiments.
An exact incumbent/transfer control plus those three tests seed the next focused
campaign; two more Claude proposals follow measured seed feedback.

The supervisor rotates Exchange2, Leela and GCC train workloads and four
hypothesis families: branch/code growth, integer expression costs, and
allocation/memory/scheduling pressure, plus larger inlining/unrolling interventions.
Each full profile is validated against
explicit enumerated axes. GCC revision, ISA/ABI, baseline flags, libraries and
the matching MegaBOOM AGFI/driver remain fixed. A compiler can transfer to a new
workload; its score and confirmation status cannot. Novelty constraints reserve
previously attempted profiles per workload. There is no trained predictor or
assumed transfer from generic kernels.

Source-derived MegaBOOM V3 capacities guide hypotheses: four-wide decode,
128-entry ROB, integer/memory issue widths 4/2, 128 physical registers per class,
32-entry load/store queues and eight D-cache MSHRs. These do not establish
measured bottlenecks. Every proposal must state an expected code change and how
the experiment could falsify it. Static pressure is not physical occupancy, and
the measured applications did not exhibit GPR/FP register parking.

Each selected confirmed compiler receives a separate paired reference check on
both physical workers, with opposite execution orders. Original and selected
compiler are compared on each worker. Reference results never enter train
review/proposal data. Reference measurement overlaps CPU preparation of the next
campaign. Validated, matching preparation artifacts are copied privately to
avoid rebuilding common controls; ordinary copies prevent revalidation from
mutating the historical files. The controller still checks compiler manifests,
archive bytes, actual executable fingerprints and native test outputs. Timing
cache reuse requires complete instance/software/hardware/input/repeat keys,
raw output hashes and native validation; reuse is not an independent sample.

```bash
source /private/run/env.sh
python -u -m examples.boom_cost_model.autopilot \
  --initial-run /private/current/run --directory /private/autopilot
```

Use a dedicated window in the user's tmux. `state.json` records the current
phase, observed work, reviews and any blocker. Every `round-*` saves its decision,
config, preparation reuse, launch command and campaign log. Reference results
are under `reference-validation/`, separate from feedback.

To stop, create `STOP` in the supervisor directory. During an owned campaign,
the supervisor signals only its child process group and waits for active work to
drain. While observing the original user-launched controller, STOP prevents
succession without signaling that controller. SIGINT/SIGTERM also request this
drain. A supervisor lock prevents duplicate supervisors; existing campaign locks
prevent duplicate controllers.

The supervisor waits on failed read-only AWS/SSH idle checks. A failed or
incomplete experiment, stale result, invalid plan, missing artifact or low local
disk space blocks further launches and records the reason. It never disables
authentication, changes networking, takes over an occupied slot, deletes data,
or launches replacement instances. Inspect logs and drivers before resuming a
blocked experiment. Interactive authentication can still require the owner.
Building and validating useful new workloads can leave unavoidable FPGA gaps;
the supervisor does not replay known timings merely to show utilization.

All SPEC source, binaries, inputs, outputs and related raw artifacts stay in
private run directories. Results remain non-reportable research estimates.

## Deadline mode

An optional `--settings /private/settings.json` enables `deadline_mode`. Its
default target schedule gives two of every three rounds to the much shorter
Exchange2 train workload, with Leela as a second workload. Hypothesis families
continue to rotate. Regular rounds use a control, two Claude-planned tests, and
one proposal after those measured outcomes. Three-key train confirmation and
every correctness/collection/network gate remain unchanged.

The `codegen-growth` family is a structured control/inline/unroll/combined
factorial with no redundant model calls after exhausting those four profiles.
Inlining raises automatic inline-insn limits from30 to180 and unit growth from40
to80. Ordinary loop unrolling is disabled in the measured baseline O3 query;
the unroll intervention enables it with instruction budgets256/128 rather than
200/80. Both retain the confirmed scheduling/IRA/peel64/jam1 policy. These are
experimental BOOM target defaults under fixed command-line flags, not hardware
latency estimates. Old policy fragments and compiler identities stay unchanged.
New compilers must query actual defaults, unchanged explicit Rocket behavior,
and explicit-option precedence before workloads are built.

`prepare_seed_count` prepares all structured seeds during an existing validation
phase. Timing caches still require full key/raw/native revalidation.
`reference_policy: milestone` validates the first selected confirmed compiler,
then checks a new compiler only after the configured train-speedup threshold
and time interval. The staged deadline settings use1.05x and24hours. Existing
reference runs finish intact; their results remain excluded from proposals.
An existing `reference_root` can be shared for validated milestones without
repeating completed measurements. `external_stop_controls` preserves the
previous supervisor's STOP path during an operational handover.

Train run-controller budgets now allow at least24hours, following the user's
request to avoid short timeouts. Leela's original-GCC train baseline completed
after about6,311 wall seconds, beyond the earlier5,400-second manager limit.
Monitoring/status queries remain read-only. A manager timeout is not evidence
of a guest correctness failure: preserve the image, verify driver exit and
matching hardware/executable, recover output read-only, and run native comparison
before registering any recovered measurement. Keep the original failure intact;
reuse the same physical-worker/input/repeat key, not a new independent sample.

After inspecting a failure, `--resume-run /private/recovery/run` lets the
supervisor own and drain the resumed controller. Its config must live at
`/private/recovery/config.json`; an existing immutable snapshot must match.
Active or already-completed runs are rejected. The ordinary supervisor still
blocks on an unexpected missing result; resume is an explicit operator action.

Adaptive campaigns now request feedback after two completed profiles including
the control, while labeling the remaining profiles pending with no invented
scores. `feedback_min_completed` can request a larger barrier; historical
pressure/factorial modes retain their original barriers. `scheduling.json`
records the effective policy. Existing running processes keep their loaded
policy until their current campaign ends. This avoids leaving one FPGA waiting
for a long third seed before the fourth proposal can even be prepared.

Adaptive model responses use bounded knob deltas. The driver reconstructs every
frozen field from the confirmed anchor, validates all bounds, and rejects unknown
axes. Legacy complete-profile responses remain readable and strictly validated.
An unconfirmed faster screening profile never silently replaces the control.
The optional `joint-costs` family explicitly explores its arithmetic/branch and
allocation interactions while retaining the confirmed control. Rejected model
responses are saved and never executed.

## Model and effort policy

Optional settings `llm_model` and `llm_effort` pin the model and CLI effort for
future planner/feedback calls. The current private policy requests
`claude-opus-5-5` and `xhigh`. Each request saves `llm-settings.json` and passes
an explicit `--effort` flag; API-only thinking parameters do not configure the
CLI backend. Authentication continues through the user's Claude CLI session.

Do not rewrite historical model provenance or an invoked config snapshot.
Queued/resumed configs that differ from the requested policy are refused.
Clone the config into a fresh run and copy only validated benchmark preparation
artifacts, excluding old invocation/config snapshots. Compiler/program identity
and native tests are rechecked. Pre-existing structured seeds keep their origin;
the new model generates subsequent proposals. An owned coordinator can change
at a quiescent boundary while existing FPGA measurements finish unchanged.
