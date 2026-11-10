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
