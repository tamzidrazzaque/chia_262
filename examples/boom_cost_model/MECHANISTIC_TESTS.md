# Three independent tests at the confirmed BOOM anchor

The recent loop/unroll/inlining and memory-cost searches did not pass the
incremental promotion threshold. The next portfolio changes three different
compiler decisions. The latest confirmed anchor is selected after the active
round finishes; a screening minimum never silently becomes the control.

| Treatment | Single intervention | Expected code change | Evidence against the hypothesis |
| --- | --- | --- | --- |
| Integer selection | Multiply heuristic3 to4, both integer modes | Different multiply versus shift/add sequences in solver functions | Unchanged relevant code, or slower correct FPGA execution |
| Scheduling | Disable scheduling before register allocation; keep post-allocation scheduling | Different live ranges/allocation, potentially less stack traffic on this out-of-order target | No relevant change, increased stack traffic, or slower execution |
| Control-flow formation | Enable tail duplication with GCC's existing estimated probabilities | Straighter superblocks and different transfers, with potentially larger code | No relevant change, or a footprint increase without a runtime benefit |

The measured winning binary contains85 static multiply instructions across the
named digit-solver functions and clones. Its large solver function is about44KB,
against the pinned32KiB instruction cache. These observations justify tests;
they do not establish executed instruction counts, cycle shares or cache misses.
Saves/restores must not be labeled exact spills. Diagnostics of a different
compiler do not transfer automatically to a newly selected anchor.

These are **BOOM compiler-policy experiments**, extending beyond scalar cost
table edits. The scheduling treatment intentionally removes the pass where
the retained pressure-aware scheduling option operates; it is not a pressure
algorithm comparison. The tracing treatment uses no measured profile or PGO.
See the pinned [GCC13.2 optimization documentation](https://gcc.gnu.org/onlinedocs/gcc-13.2.0/gcc/Optimize-Options.html)
for the scheduling passes and tracer transformation.

The named policy variants inherit every loop/inlining default of the anchor.
All scalar/move costs except the named multiply treatment, the scheduling DFA,
compiler revision, external flags, ISA/ABI, libraries and FPGA image stay fixed.
Rocket defaults and explicit user-option precedence are verified inside each
actual compiler. Scheduling verification checks that the post-allocation pass
stays enabled. Historical policy fragments and compiler identities are unchanged.

The portfolio has five slots: confirmed control, three isolated treatments,
and one evidence-guided Opus/xhigh follow-up. Completed controls may be reused
only through the full validated measurement-cache key. The follow-up can combine
multiply selection with one new policy when the completed single-treatment
evidence supports it; it cannot combine both new passes or invent scores for
pending work. This family waits for the control and all three treatments before
requesting its combination; the short scheduling barrier is intentional.
Already measured profiles and identical executables are excluded.

Every candidate passes test inputs in QEMU and native output comparisons before
FPGA screening. Promotion requires the existing1% original and0.5% incremental
speedup thresholds and repeat confirmation. Any qualifying new winner receives
held-out reference validation; reference scores never enter planner feedback.
Record negative results as well. All SPEC timings are partial-suite FPGA
research estimates, not official SPEC scores. Licensed artifacts remain private.
