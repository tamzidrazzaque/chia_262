# One-day result priorities

The immediate deliverable is a correctness-checked improvement on this fixed
MegaBOOM configuration, with held-out evidence and complete compiler identities.
The current confirmed Exchange2 train improvement is 5.70%. A newer branch-cost-12
candidate screened at 76.82 s versus 77.68 s incumbent and 82.11 s original:
approximately 6.89% speedup over original, still pending repeat confirmation.
These are partial-suite research estimates, not official SPEC scores.

1. Finish the active confirmation without interruption. Original and incumbent
   controls have three validated repeat keys each. The challenger needs its
   remaining confirmation samples before promotion; cached samples stay labeled.
2. Validate the confirmed best on reference inputs on both F2s. Prepare images
   speculatively on CPU while train confirmation runs; preparation does not
   confer selection or accept a reference score. Reference timings stay outside
   proposal generation. Previous selected-compiler reference jobs took about
   five hours each; run them in parallel. Reuse original reference controls only
   when full software/hardware/worker/input/repeat keys, raw bytes and native
   checks match. A cache miss reruns the control, never substitutes its timing.
3. During reference execution, prepare the seven-profile seed set for the
   structural frontier in `NEXT_ROUND.md`. The six changes plus one adaptive
   follow-up run on two F2 workers after the control. Choose the anchor from
   confirmed results, including an intervening winner; do not silently reuse
   speculative compiler bytes built with different scalar costs.
4. Follow with a short interaction campaign combining structural settings,
   branch-cost choices (including 16 and 24) and spill-load heuristics. The measured branch-cost-12 point
   motivates a nonmonotonic interaction test; the model must explain a change
   in generated code and keep every unlisted compiler field fixed.
5. Prioritize held-out validation of the best distinct compiler over further
   small scalar searches. Reference milestones have a six-hour cooldown so
   near-adjacent winners do not consume the whole remaining day. Keep sufficient
   time for the final validation and publish both wins and failures.

For this sprint, pause the unproductive Leela integer-cost searches and focus
the short hardware feedback loop on Exchange2. Do not add slow, unqualified
targets merely for variety. Do not use generic microkernel rankings that failed
to predict these application results.

The corrected cache diagnostic ran on the otherwise idle worker while the
active controller confirmed on the other worker. Its immutable config pins
confirmation to worker1, all screening is finished, and final_ref is false;
read-only idle and full hardware/cloud guards precede the separate job. Remove
the redundant two-worker diagnostic barrier. This diagnostic passed 48 checks
on one F2, but it is not an application or compiler speedup:

| Working set | Pointer chase, guest ns/load | Stream, guest ns/load |
| --- | --- | --- |
| 16 KiB | 5.90 | 1.04 |
| 32 KiB | 6.10 | 1.03 |
| 64 KiB | 25.57 | 7.48 |
| 16 MiB | 144.78 | 21.29 |

These are medians of three calibrated batches. The capacity transition near
the 32 KiB L1 is visible; TLB, cache and memory-parallelism effects are not isolated
by this test. Use a compiler-sensitive locality workload before crediting a
cache-oriented compiler change. No raw SPEC outputs enter the public data.

Operational priorities: overlap CPU preparation with FPGA execution, preserve
all correctness/identity/network protections, surface expired authentication,
and skip optional work when its safe overlap window has ended. Continuous
launch authorization remains in force until the owner stops it. The one-day
horizon is a research priority, not permission to terminate live measurements
or fabricate a result at a time limit.
