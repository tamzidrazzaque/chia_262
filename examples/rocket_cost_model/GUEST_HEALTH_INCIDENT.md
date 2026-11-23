# Guest health investigation, 2026-11-23

The manager's `running` state did not establish that Linux was healthy. The
monitor now checks the exact dispatched attempt, resolves its admitted worker,
and binds the UART to a live driver with the matching job argument. It reports
kernel panics separately from quiet output. Baseline qualification is visible
before the adaptive runner starts. A completed individual sample is displayed
without implying that its pair has completed.

## NAB: confirmed guest panic, root cause unresolved

The fresh stock-vector control panicked before `/root/saturn-spec/result` or
`work` was created. Thus neither the RVV probe nor NAB started in this attempt.
The failure is independent of the new GCC cost-model candidate and unrelated
to the earlier output-tolerance correction.

Linux reported an illegal instruction in `vfs_statx`, with EPC
`0xffffffff801c4e50` and trap value `0x67110007`. Disassembling the accepted
kernel shows a 32-bit branch at `0xffffffff801c4e4e` and the next instruction at
`0xffffffff801c4e52`: the recorded EPC is in the branch's second halfword.
The code bytes printed by Linux agree with those kernel bytes. This supports
investigating control-flow/fetch/exception handling, but does not identify the
first divergent instruction or prove a particular RTL defect. No RTL fix or
replacement FPGA image has been qualified by this investigation.

Raw UART, launch commands and process evidence were archived privately before
terminating the exact failed driver. Its executable hash, job argument, PID and
fatal UART evidence were checked again immediately before termination. The
original campaign drained to `blocked` and produced no accepted sample.
A fresh scalar/vector qualification pair was launched on the same admitted
worker and platform. An activation watcher permits the existing continuous
loop to resume only after both baselines pass, using fresh attempt identities.
This is a recovery test, not evidence that the kernel fault has been repaired.

## MCF: long measurement, not a confirmed failure

The quiet UART initially made forward progress uncertain. Read-only inspection
of its guest filesystem showed a passing VLEN probe and a benchmark invocation.
The candidate subsequently completed correctly at 104,682,814,007 whole-boot
cycles, and the campaign advanced to its fresh stock-vector control. Historical
accepted MCF runs take approximately 2,430–2,470 host seconds per task, so long
UART silence during this workload is expected. No driver was stopped on the
basis of silence, and there is no paired speedup conclusion yet.

## Execution fix

New native workload tasks run under a watchdog. A confirmed kernel panic or
explicit failed-simulation marker causes it to archive raw UART, stop only the
admitted driver and reject the task. A live process or a zero FireSim manager
exit cannot override fatal guest evidence. Observer/SSH failures and UART
silence alone never authorize killing a task. Quiet-output warnings use a
one-hour threshold for MCF and 30 minutes for NAB; these are observation
thresholds, not correctness or performance cutoffs. Existing guest images,
kernel, driver and FPGA bytes were not changed.
