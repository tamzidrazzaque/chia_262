# Retuning costs under the confirmed BOOM policy

The pressure/growth refinement completed without improving the 80.71s Exchange2
train incumbent (82.11s original GCC; 1.017346x speedup). Scheduling-only reached
80.90s, IRA-only 81.13s, tighter peeling 83.11s and looser peeling 82.16s.
Restoring the unroll/jam factor generated identical executable bytes and was
skipped. Two Claude alternatives reached 81.38s and 81.56s. All saved native
correctness and collection checks passed. The incumbent now reproduces on both
physical workers. Reference inputs remain untested for this winner.

`campaign_kind: "cost-refine"` freezes that incumbent's model scheduling-pressure
algorithm 2, IRA loop pressure, complete-peel budget 64 and unroll/jam factor 1.
It retunes cost weights under this policy. Measurements under older policies
provide context, not predicted scores. The scalar heuristics are not measured
hardware latencies, and generic microkernel ranking remains unvalidated.

The private config supplies a complete `anchor_proposal`, enumerated `cost_axes`
and `cost_seeds` containing `knobs` and `rationale`. The first seed must be the
unchanged anchor. Each response must preserve all unlisted fields and policy.
The adapter supports bounded branch, memory, integer multiply/divide and GPR
load/store costs; paired integer costs must change equally in both modes.
For the prepared round, integer divide, floating and cross-file costs stay fixed.

| Seed | Change from incumbent |
| --- | --- |
| 0 | Exact incumbent control |
| 1 | General memory cost 7 → 5 |
| 2 | GPR load/store costs 8/6 → 4/4 |
| 3 | Branch cost 8 → 4 |
| 4 | Integer multiply costs 4/4 → 3/3 |
| 5 | Combine seeds 1, 2 and 3 |

Two authenticated Claude CLI proposals follow all six seed outcomes. The prompt
contains numeric evidence, current results and pending profiles. It permits
data-only JSON within enumerated axes, with no executable tools, commands,
patches or new flags. Exact duplicate profiles and executable bytes are skipped.

The completed train-confirmed primary archive remains pinned by result hash,
compiler identity and exact hardware manifest. Optional `incumbent_supporting_runs`
provides at most four additional completed archives, each pinned by result hash
and required to select the same compiler/profile on the same hardware. This
allows reuse of the latest incumbent control without mistaking a completed
no-improvement round for new confirmation. Only explicit original/selected
control phases are imported. The full instance/software/hardware/input/repeat
key, raw-output hashes and fresh native comparison still gate reuse. Cache
records do not increase the independent sample count.

Selection and paired confirmation follow `REFINEMENT_CAMPAIGN.md`: require at
least 1% over original GCC and 0.5% over the incumbent, then compare original,
incumbent and new winner using three repeat keys on the configured worker.
No qualifying gain retains the incumbent without redundant confirmation. The
prepared round keeps reference validation separate (`final_ref: false`). These
are research estimates, not reportable SPEC results or a validated learned model.

The owner launches the existing controller in their own tmux:

```bash
source /private/run/env.sh
python -u -m examples.boom_cost_model.focused_campaign \
  --config /private/cost-retune-config.json --run-dir /private/cost-retune-run
```

The command prepares compilers and workloads, enforces test/QEMU/native gates,
and dispatches train evaluations to both F2s. Compiler revision, baseline flags,
ISA/ABI, libraries and matching AGFI/driver stay fixed. Existing authenticated
localhost Ray, strict SSH/tunnels, AWS policy and occupied-slot checks remain
mandatory. Licensed workloads and raw artifacts remain private. Agents prepare
and inspect; they do not start these controllers.
