# Beyond the cost-neighborhood plateau

The completed scalar-cost and loop-budget searches retain the confirmed
Exchange2 incumbent. The next portfolio holds its costs, move costs, existing
unroll/inlining defaults and pressure policy fixed while testing five different
compiler decisions. These are broader compiler-policy experiments, not pure
scalar cost-table changes.

| Isolated treatment | Change | Check before interpreting a timing |
| --- | --- | --- |
| Live ranges | Enable live-range shrinkage | Allocation and static stack-reference changes |
| Allocation regions | IRA `one` to `all` | Loop allocations and extra moves/stack references |
| Specialization | Unswitch budget50 to400 | Duplicated loop bodies and eliminated invariant branches |
| Specialization counterpoint | Disable unswitching | Footprint reduction versus additional dynamic branches |
| Cloning | Disable IPA constant-propagation cloning | Solver clones, call sites and function footprint |

The actual pinned compiler reports function-wide IRA and an unswitch budget50.
The large solver's static footprint motivates these alternatives; neither static
size nor stack-reference counts establish instruction-cache misses, dynamic
spills or cycle bottlenecks. See the pinned
[GCC13.2 option descriptions](https://gcc.gnu.org/onlinedocs/gcc-13.2.0/gcc/Optimize-Options.html).

The campaign has nine slots: the confirmed control, five isolated treatments,
then up to three train-feedback proposals from bounded combinations. Feedback
waits until all six initial points complete. Test inputs in QEMU and native SPEC
output validation precede FPGA train timing. Full validated cache keys and exact
ELF deduplication remain mandatory. A distinct ELF is not proof of the proposed
mechanism. No change to source revisions, external flags, ISA/ABI, libraries,
scheduling DFA or FPGA image. Every actual compiler checks BOOM defaults,
unchanged Rocket defaults and explicit user-option precedence.

An8% throughput speedup over the original means Exchange2 train at most
82.11/1.08=76.0278 seconds and held-out reference at most919.62/1.08=851.50 seconds.
The aim is not an observed result. Promotion requires existing repeat thresholds;
reference inputs remain validation-only and never feed the planner. Results are
partial-suite research estimates, not official SPEC scores. Licensed artifacts
and site configuration remain private.

The completed five-treatment portfolio retained the control. Disabling cloning
regressed from76.82 to118.98 seconds on Exchange2 train; larger unswitching plus
live-range shrinkage gave77.13 seconds, still slower than the control. IRA-all
and two related combinations produced duplicate application executables and
were skipped, not measured as failures. This does not establish a cache or
allocation bottleneck.

The subsequent `cloning-frontier` is a four-point factorial: control, IPA cloning
unit growth10 to50, evaluation threshold500 to125, and both. The actual pinned
compiler reports defaults10 and500. The pass stays enabled; costs, existing
unrolling/inlining and pressure settings remain fixed. Inspect actual clones
and call sites, then test correctness and hardware time. More aggressive
specialization is a hypothesis, not an achieved speedup. The initial factorial
is deterministic and is not attributed to the LLM.
