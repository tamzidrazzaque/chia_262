# Next experiment: structural frontier

The confirmed Exchange2 train winner is 77.68 seconds versus the original
82.11 seconds (5.70% speedup). Enabling ordinary unrolling improved the earlier
80.11-second compiler to 77.68 seconds; recent scalar-cost edits improved the
incumbent by less than 0.5%. A wider code-generation intervention is a better
next hypothesis than another narrow scalar-cost neighborhood.

The next structural campaign targets Exchange2, with the latest **confirmed**
compiler selected after the active campaign finishes. Original GCC remains a
separate control. Keep the source, inputs, GCC revision, ISA/ABI, external
baseline flags, libraries, scheduling DFA and all scalar/move/pressure settings
fixed. Change only named BOOM target defaults for ordinary unrolling/inlining.

| Profile | Max / average unroll budget | Auto-inline budget / unit-growth limit | Question |
| --- | --- | --- | --- |
| Confirmed control | 256 / 128 | 30 / 40 (verified original defaults) | Repeat the known winner |
| A: unroll_small | 128 / 64 | Original defaults | Does a smaller loop body preserve useful parallelism? |
| B: unroll_large | 512 / 256 | Original defaults | Does doubling the budget expose more useful independent work? |
| C: unroll_xlarge | 1024 / 512 | Original defaults | Is there further headroom, or does footprint/pressure dominate? |
| D: inline_selective | 256 / 128 | 80 / 30 | Does moderate inlining expose optimization opportunities without the earlier 180 / 80 expansion? |
| E: inline_selective_large | 512 / 256 | 80 / 30 | Test the inlining/unrolling interaction against B and D |
| F: inline_small_large | 512 / 256 | 20 / 10 | Can restricted inlining balance larger loop bodies? |

These are GCC heuristic budgets, not literal unroll factors, measured cache
occupancy or promises about instruction counts. Explicit compiler options still
override these defaults. Existing presets and their compiler identities remain
unchanged.

The large-unroll compiler was built speculatively in the actual compiler worker
against the currently confirmed anchor. Its effective defaults were verified
as 512/256, with inline30/growth40, unchanged Rocket defaults and explicit-option
precedence. The next campaign still chooses its anchor after the active run;
an intervening confirmed winner may require rebuilding these speculative bytes.

One additional Opus/xhigh proposal follows measured seed feedback. Two extra
choices are reserved for it: 80/30 inline with 1024/512 unrolling, or 20/10
inline with 128/64 unrolling. Those represent escalation and footprint reduction;
neither has a preassigned score. Structured seeds are agent-reviewed ablations,
not retroactively attributed to Claude. The campaign has seven seed profiles
including the control and eight total profile slots.

Every candidate must pass effective-option/identity verification and SPEC test
inputs in QEMU with native comparisons. Exact duplicate executables are skipped
before FPGA measurement. Changed hot-code size, branches and static allocation
evidence guide interpretation; QEMU execution counts are not cycle shares.
QEMU timings and the previously unsuccessful generic-kernel ranking do not
prune or train hardware performance predictions.

Both F2 workers screen distinct candidates on train inputs. Promotion retains
the existing original-baseline and incremental thresholds and three repeat
confirmation keys. A small new minimum is not a confirmed winner. Validate a
new winner on held-out reference inputs before claiming generalization; no
reference timings enter model feedback. The stretch goal is a materially larger
gain, not a promised percentage.

The separately queued cache-capacity sweep is diagnostic only. A compiler-
sensitive locality workload (for example, a multidimensional stencil with
resident and above-LLC working sets) needs its own verified source, code-change
and hardware-sensitivity evidence. Do not optimize the deliberately fixed
pointer-chase diagnostic or assume Exchange2 strains the data cache. Pause
further narrow Leela integer-cost searches until there is a new justified
mechanism; its latest candidates did not beat the original.

PGO/LTO could be useful as a separate performance-ceiling experiment, but they
change the optimization recipe and require their own matched baseline. They are
not enabled by this cost-model campaign.

Reference: [GCC 13.2 optimization parameter definitions](https://gcc.gnu.org/onlinedocs/gcc-13.2.0/gcc/Optimize-Options.html).
