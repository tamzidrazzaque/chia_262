# Boot failure causal audit

The earlier statement that guest layout normalization fixed MCF's boot problem
was stronger than the experiment supported. Layout and the image were changed
together. A subsequent successful run establishes a working image, not the
cause of the earlier failure.

## Checked evidence

| Case | Kernel symbol | Reported EPC | Containing 32-bit instruction begins | Trap value |
|---|---|---|---|---|
| Original MCF role 3.2 and exact symptom retry | `kobject_get` | `0xffffffff8078cc5a` | `0xffffffff8078cc58` | `0x60e20207` |
| NAB stock-vector control | `vfs_statx` | `0xffffffff801c4e50` | `0xffffffff801c4e4e` | `0x67110007` |

Both failures report instruction exceptions at a branch's second halfword. The
printed bytes agree with the corresponding kernel disassembly. This is a
shared symptom, not yet a root-cause attribution to Saturn, Rocket, Linux,
FireSim or the packaging code.

Read-only filesystem checks passed for the retained failed MCF images, the
layout-matched MCF image, and the passed/failed NAB images. All use the same
accepted boot binary. Passed and failed NAB source images still match their
receipts; BusyBox, inittab, rcS, S99run, mdev/network startup, hostname and the
benchmark executable compare identically. The workload fingerprint also
matches. Their 37-line runner scripts differ only in the run-identity JSON
line. Thus no filename/invocation mismatch analogous to the earlier producer
change was found in the NAB control.

A relevant historical [Chipyard clock-crossing issue](https://github.com/ucb-bar/chipyard/issues/2103)
was checked rather than assumed applicable. Its linked [Rocket fix](https://github.com/chipsalliance/rocket-chip/pull/3693)
is already an ancestor of the pinned source. The deployed Saturn configuration
uses `WithFireSimConfigTweaks`, not the test-chip variant discussed there.
That report is not evidence that our image has the same fault.

## Controlled next test

Use preserved failed image A and preserved successful image B on the same
admitted worker, kernel, driver, FPGA image and memory model:

1. Replay A without tracing.
2. Replay B without tracing.
3. Replay A again without tracing.
4. Replay A with PC-triggered TracerV around the failing kernel function.

Do not rebuild the guest or change filenames between these attempts. Each
replay gets a separate guarded audit directory, fresh preflight and worker
lease. A diagnostic host-time limit bounds the boot test. Changing only a diagnostic
suffix is common to untraced controls. Tracing is
introduced separately so its effect is observable.

`saturn_boot_replay.py` reuses the accepted native adapter and execution guard.
It rechecks immutable image bytes on the manager and worker, preserves original
attempt records, and writes explicitly diagnostic completion records that the
performance collector rejects. Raw traces remain private. This test can
separate reproducible image-sensitive failure from changing initialization or
launch state; the first divergent instruction still requires trace analysis.

The existing MCF campaign continues because its latest candidate completed
correctly. NAB's current scalar/vector qualification continues, while candidate
auto-start is held for this diagnosis. Its fresh scalar qualification already
passed at exactly 36,937,795,127 cycles, matching its earlier pilot. Successful
qualification alone will not be described as a repair of the kernel fault.

## Rejected initial replay setup and separate correctness failure

The first four replay attempts stopped before the relevant boot interval.
The accepted FireSim scheduler parses `+max-cycles` using 32-bit `atoi`.
The requested 6,000,000,000 wrapped to 1,705,032,704, and UART reports timeout
after 1,705,032,705 cycles. Those attempts and the header-only trace are retained
but provide no A/B boot conclusion. Replay now leaves target plusargs unchanged
and uses an explicit 300-second host budget with guarded evidence capture.
Normal performance runs do not use that diagnostic deadline.

The fresh NAB vector qualification completed but failed output validation.
The installed official SPEC comparator independently rejected it using
`--reltol 0.01 --skipreltol 2` (without missing-line relaxation). Five numeric
values differ; four exceed 1%, with a maximum relative difference of about
7.68%. This is separate from the kernel panic and is not merely the stricter
local validator rejecting an official pass. Its raw output remains private.
