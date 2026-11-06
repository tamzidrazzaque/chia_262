# Role-2 scalar multiply replay diagnosis

The first directly observed address-chain divergence is the first `mul a2,a2,a3`
at PC `0x11e84`, in the matching loop context `s5=5`, `t2=9`, `VL=4`.
QEMU gives `a2=0x510`; FPGA gives `0x5100`. The following address add consumes
that wrong result correctly. The credible root cause is Rocket/Saturn replay
integration around the iterative MulDiv unit, rather than vector arithmetic,
an invalid compiler-generated address, or a false memory fault on a valid address.

## Discriminating hardware evidence

Two bounded diagnostic boots ran six separate checkpoint cases. Five captured
valid state; one pre-multiply case returned capture status 11 without a register
snapshot and is excluded. Both boots passed the accepted platform/probe and
shutdown checks; read-only preflight verified the worker idle after each.
All text changes were private child-process mappings. The on-disk worker ELF
was read back afterward and still has the exact frozen role-2 SHA-256.

| First-iteration diagnostic | QEMU a2 | FPGA a2 |
| --- | --- | --- |
| Original multiply, stop immediately afterward | `0x510` | `0x5100` |
| Replace multiply with `addi a2,a2,1` | `0x145` | `0x145` |
| Multiply from stable source `a0` instead of destination `a2` | `0x510` | `0x510` |

All three controls match in `a0=0x144`, `a3=4`, `a4=0xf1924`, `t2=9`,
`s0=0xf1910`, `s1=0x144`, `s5=5`, `VL=4`, `VTYPE=0x17`, and `VSTART=0`.
The original result is exactly `0x144 * 4^3`, not `0x144 * 4`. This is an
arithmetic equivalence, not an internally measured request/retirement count.
The add-immediate control does not accumulate extra updates. The stable-source
multiply is correct because repeated writes cannot feed its destination back
into its next execution. These controls distinguish iterative-unit replay side
effects from a general ALU or multiplier arithmetic failure.

A separate checkpoint after the original address add observes `a4=0xf6a24`,
exactly `0xf1924 + 0x5100`. The authoritative core's final `0x144f6a24` is
consistent with that observed first update plus an inferred second update of
`0x14400000`. The second update was not directly checkpointed. The eventual
strided-load SIGSEGV is downstream of corrupted scalar address state.

## Exact pinned RTL mechanism

The accepted-source generated RTL instantiates Rocket's iterative `MulDiv_1`,
not the pipelined multiplier. The source audit identifies this cancellation gap:

- `PipelinedFaultCheck.scala:120` routes non-unit-stride loads through the IFC.
- `saturn/rocket/Frontend.scala:48` blocks younger scalar operations while that
  iterative checking/replay activity is in progress.
- `RocketCore.scala:702-713` includes vector blocking in M-stage replay, but
  `div.io.kill` uses `killm_common`, which omits those vector replay conditions.
  A request accepted in the preceding execute stage can therefore survive the
  replay of its owning scalar instruction.
- `RocketCore.scala:785-795,823-831` accepts surviving MulDiv responses into the
  long-latency integer writeback path. That path can update the register file
  independently of the replayed instruction's ordinary WB retirement.
- `Multiplier.scala:161-163` cancels the iterative unit only when its kill input
  is actually asserted. A subsequent replay can read the already changed RMW
  destination and multiply it again.

The generated RTL repeats this same kill/replay wiring; its source and audit
hashes are recorded privately. No accepted RTL/source pin, image, driver, kernel,
Linux base, or baseline executable was changed.

This is a credible causal diagnosis supported by hardware controls and the
pinned implementation. It is not a cycle-exact waveform proof of every RF
write-enable. The checkpoints localize the address corruption; they do not
claim a full-program trace proves that every earlier vector bit matched QEMU.

## References and limits

The accepted image's TracerV bridge exposes PC/cycle tracing without RF write
values. The reconstructed generation artifacts contain no usable RF AutoILA
probe metadata. Those facilities would not directly supply the missing operand
and writeback observations, so process checkpoints supplied the discriminating
state without changing the image.

The [upstream frontend description](https://github.com/ucb-bar/saturn-vectors/blob/master/docs/tex/frontend.tex)
describes killing/replaying younger scalar work while IFC is busy. The
[architectural-test report](https://github.com/chipsalliance/rocket-chip/issues/3840)
uses the same Rocket revision and reports other integration defects, but does
not establish or fix this multiply cancellation failure. No unrelated upstream
patch was substituted into this experiment.

QEMU reference controls used an extracted, signed-distribution Ubuntu qemu-user
8.2.2 package (GPL/LGPL licensing reviewed); no system/project dependency or
protected component was replaced. Only private diagnostic ELF copies were
patched for its variant controls. Initial failed GDB text-write attempts are
retained privately and excluded; the final references used verified patched
copies. No QEMU wall time is performance evidence.

## Stop point and correction boundary

Stopped with the first address-corrupting instruction localized and a credible
integration/replay cause. A correction must cancel or invalidate an accepted
iterative MulDiv request when vector-side replay kills its owning scalar work,
and prevent any stale response from changing the register file. Validate that
contract with RTL assertions and the directed controls before rerunning frozen
role 2. This document does not apply or claim validation of a hardware fix.
Changing the accepted image/RTL build requires an operator methodological decision.

All diagnostics remain excluded from performance collection. No role 3 or
repetition campaign ran. Raw snapshots, core, licensed files, failed attempts,
images, QEMU/debugger logs and source audit remain private under
`/home/ubuntu/cs262_compiler/saturn-spec-lane/debug-010/` and `debug-011/`.
The original core remains in `diagnostic-009/`. Sanitized proof is in
`saturn-role2-replay-diagnosis.json`; focused lane/diagnosis tests: 60 passed.
