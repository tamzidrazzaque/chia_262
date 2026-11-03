# Refining the confirmed pressure-policy gain

The preceding pressure campaign completed all six proposals and three-key train
confirmation. Original GCC measured 82.11 guest seconds and the combined
pressure/compact policy measured 80.71 seconds in every confirmation sample:
1.017346x speedup on Exchange2 train. Native comparison and collection gates
passed. Reference inputs remain untested; no official SPEC metric is claimed.
The winner was the structured combined seed. Claude's weighted-scheduler
follow-ups regressed; a learned performance predictor has not been established.

`campaign_kind: "pressure-refine"` keeps its exact compiler as the incumbent.
All scalar/move costs, baseline driver identity, GCC revision, command-line flags,
ISA/ABI, runtime libraries and FPGA image remain fixed. Only the bounded BOOM
optimization-default policy varies.

| Seed | Scheduling pressure | IRA loop pressure | Peel budget | Unroll/jam factor |
| --- | --- | --- | ---: | ---: |
| 0: winner control | Model (2) | On | 64 | 1 |
| 1: scheduling only | Model (2) | Existing default | 64 | 1 |
| 2: IRA only | Existing default | On | 64 | 1 |
| 3: tighter expansion | Model (2) | On | 32 | 1 |
| 4: looser expansion | Model (2) | On | 128 | 1 |
| 5: peel-only constraint | Model (2) | On | 64 | 4 |

After these six outcomes, two Claude CLI proposals use measured feedback and the
previous round's full numeric history. Six named growth presets combine with
three pressure-algorithm choices and two IRA choices (36 bounded regimes).
Previously tested non-control policies are reserved to prevent needless retests.
Pending proposals are labeled pending. No reference inputs or inferred cycle
costs enter feedback. Identical executables are skipped before F2 timing.

The incumbent archive is pinned by its result hash, passing confirmation status,
compiler ID, policy and exact hardware manifest. Its original/control cache
records may be imported only from explicit phases. Reuse still requires the
complete software/runtime/hardware/instance/input/repeat key, raw output hashes
and fresh native comparison. A reused record is not a new independent sample.
The immutable incumbent compiler ID and all backend source hashes are preserved.

The original GCC remains the measurement anchor. A new policy must improve at
least 1% over original GCC and 0.5% over the current incumbent to qualify for
promotion. Otherwise `incumbent_retained` is true and the old winner is not
needlessly reconfirmed. A qualifying new policy gets three-key comparison with
both original GCC and the incumbent on one verified physical worker. The prepared
configuration chooses the worker holding their previous confirmed samples,
allowing exact cache reuse. A winner found on the other worker therefore also
gets a cross-worker check during confirmation. Failed confirmation retains the
incumbent. The result records both original and incremental speedups and the
selected policy. Reference validation remains separate in this round.

The owner launches in their terminal/tmux; agents prepare code and inspect data:

```bash
source /private/run/env.sh
python -u -m examples.boom_cost_model.focused_campaign \
  --config /private/refine-config.json --run-dir /private/refine-run
```

New compilers must pass effective-option queries, explicit-Rocket/default
preservation, user-override precedence and SPEC test/QEMU/native correctness
before train measurement. Baselines remain paired with physical workers. Keep
the existing localhost/authenticated Ray, strict SSH/tunnels, matching driver/
AGFI and AWS policy checks. Do not start a second controller on occupied slots.
After a manager timeout inspect the driver before resuming. `progress.json`,
per-candidate records, compiler manifests, native reports and `result.json`
provide the audit trail. See `PRESSURE_CAMPAIGN.md` for the underlying policies.
