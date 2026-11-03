# Pressure and loop-growth campaign

After a confirmed gain, the opt-in `pressure-refine` mode separates scheduling
and IRA effects and refines growth budgets; see `REFINEMENT_CAMPAIGN.md`.

This opt-in `campaign_kind: "pressure"` expands BOOM compiler tuning into
pre-allocation scheduling, IRA loop-pressure estimates and loop-growth defaults.
It freezes the scalar and directional move/spill costs at the measured
coordinated candidate 3. The installed GCC, source revision, command-line flags,
ISA/ABI, runtime libraries and FPGA image stay fixed. Candidate optimization
defaults intentionally change; this is a compiler-policy experiment.

The setup follows the tutorial's separation of generation, build, correctness,
measurement, stored evaluations and feedback. See slides 12, 16, 23, 25–26 of
[Chia's discovery tutorial](https://chialoops.ai/slide-decks/chia-tutorial-discovery.pdf).
Its DMA example changes hardware and software together; its reported improvement
does not predict the benefit of these compiler policies.

## Initial design

| Index | Pressure | Loop growth | Role |
| --- | --- | --- | --- |
| 0 | Existing defaults | Existing defaults | Fresh incumbent control |
| 1 | GCC model algorithm + IRA loop pressure | Existing defaults | Pressure factor |
| 2 | Existing defaults | Compact | Growth factor |
| 3 | GCC model algorithm + IRA loop pressure | Compact | Interaction |

Pressure enables `flag_sched_pressure`, algorithm 2 and `flag_ira_loop_pressure`.
Compact lowers the complete-peel instruction budget from 200 to 64 and the
unroll-and-jam factor from 4 to 1. These are hypotheses motivated by high static
IRA pressure and large solver routines, not measured optimal settings. Candidate
3's scalar costs and move profile remain frozen in every proposal. The identity
policy reproduces its exact historical compiler ID and backend source hashes.

After all four seed results complete, the authenticated Claude CLI chooses two
untested bounded policies. It may vary pressure algorithm 0/1/2, IRA loop pressure
and default/compact growth: 12 regimes in total. Pending proposals are included
as pending, without fabricated timings. Claude gets numerical allocation and
functional-count evidence plus measured train results. It cannot submit patches,
commands, new flags, ISA changes or program-specific source changes. Reference
inputs stay outside its feedback.

The backend sets defaults only for `-mtune=boom`; explicit user options take
precedence. At compiler-build time, actual option queries verify the requested
policy, unchanged explicit Rocket defaults and user override precedence. The
policy/version/generated-source hash participate in immutable compiler identity.
Existing no-policy compiler identities and cached artifacts are preserved.

## Gates and execution

The existing focused controller supplies one compiler producer, native-validated
SPEC test/QEMU gates, complete executable fingerprint deduplication, two F2
consumers and independent original-GCC controls per worker. Full software,
runtime, hardware, physical-worker and repeat keys remain mandatory for reuse.
An exact historical baseline cache hit is revalidated and is not a new sample.
Incumbent and new policy measurements use the new campaign's own cache.

This first search uses Exchange2 train only. One sample screens each proposal.
A proposal clearing the original-compiler 1% threshold receives three independent
repeat keys for baseline and winner on the selected worker; exact screen/control
cache hits may supply one of those keys and do not add extra independent samples.
Pressure mode performs this confirmation even with `final_ref: false`. Failure
to confirm retains the original compiler. With reference disabled, reference
validation remains a separate experiment. This is not a full-suite score or a
generalization result.

The owner starts all controllers in their own terminal/tmux:

```bash
source /private/run/env.sh
python -u -m examples.boom_cost_model.focused_campaign \
  --config /private/pressure-config.json --run-dir /private/pressure-run
```

`--prepare-only` builds/checks the original and first two seeds without FPGA
execution; it is also an owner-launched controller. The full command performs
preparation and measurements in one run. New GCC builds and SPEC test/QEMU gates
must pass before a new policy reaches F2. A source syntax check or software unit
test alone does not establish a working new compiler or workload.

Inspect `progress.json`, `candidate-*.json`, compiler manifests, build/QEMU/native
logs, per-worker timing/correctness records and `result.json`. Ctrl-C drains
active measurements. Resuming revalidates saved evidence and refuses occupied
drivers. Authentication or infrastructure failures stop dispatch and preserve
diagnostics. After a manager timeout, inspect the owned driver before retrying.
Keep the lab's loopback/authenticated Ray, SSH tunnel and AWS network policies.
