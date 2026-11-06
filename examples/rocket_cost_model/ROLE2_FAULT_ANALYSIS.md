# Role-2 Saturn fault analysis

## Current diagnosis: scalar MulDiv replay side effects

Manager-side checkpoints localize the first observed address corruption to the
first `mul a2,a2,a3` at `0x11e84` (`t2=9`, `VL=4`), which gives FPGA `0x5100`
instead of QEMU `0x510`. Discriminating scalar controls and the pinned
cancellation/writeback wiring support an iterative MulDiv replay integration
cause. The following add is correct given its already corrupted operand.
See [ROLE2_REPLAY_DIAGNOSIS.md](ROLE2_REPLAY_DIAGNOSIS.md) and
`saturn-role2-replay-diagnosis.json` for evidence, inference limits and the
protected-build correction boundary. Two bounded diagnostic boots completed;
the worker was verified idle after each. No performance result or role 3.

Earlier observations and the corrected final-loop comparison follow.

## Matched-iteration correction (2026-11-06)

The initial report compared QEMU's first dynamic hit (`t2=9`) against FPGA's
failing final-loop hit (`t2=1`). A conditional QEMU breakpoint at `0x11e80`
with `t2 == 1` now supplies the like-for-like state:

| Register/value | QEMU matched hit | FPGA fault |
| --- | --- | --- |
| PC | `0x11e80` | `0x11e80` |
| `a4` | `0xf2344` | `0x144f6a24` |
| `s1` | `0x144` | `0x144` |
| `t2` / `a3` / VL | `1` / `1` / `1` | `1` / `1` / `1` |
| `s8` / `s5` / `s0` | `9` / `5` / `0xf1910` | `9` / `5` / `0xf1910` |
| VTYPE / VSTART | `0x17` / `0` | `0x17` / `0` |
| stack value at `sp+80` | `0x144` | `0x144` |

The core exposes the FPGA stack value directly. In the frozen instruction
sequence, `a4` begins at `s0 + 4*s5 = 0xf1924`. Each of the first two chunks
has VL 4 and advances it by `(sp+80) * 4 = 0x510`, producing `0xf2344` for the
final chunk. QEMU observes exactly that address and completes correctly.

Therefore the differing FPGA `VL=1` and `t2=1` in the earlier first-hit table
were normal final-iteration state, not evidence of divergence themselves. The
remaining divergence is the corrupted scalar address register `a4`, despite
all captured values needed to calculate it matching QEMU. This strongly points
to a Saturn/Rocket execution, replay, or scalar-vector integration defect
triggered before the failing load; it does not support GCC having generated an
architecturally invalid address. The exact first corrupting dynamic instruction
is still unknown.

## Replacement diagnostic result: execution divergence

Exactly one separately authorized replacement attempt completed the fault
capture. The previous `rcS` panic attempt remains preserved. The replacement
used the unchanged frozen role-2 ELF, official input, original diagnostic
launcher, accepted platform/boot binary, 2-GiB image and DRAM zeroing.

| Register | Recorded QEMU first hit | FPGA first-fault state |
| --- | --- | --- |
| PC | `0x11e80` | `0x11e80` |
| a4 | `0xf1924` | `0x144f6a24` |
| s1 | `0x144` | `0x144` |
| t2 | `9` | `1` |
| VL | `4` | `1` |
| VTYPE | `0x17` | `0x17` |
| VSTART | `0` | `0` |

The pre-delivery signal snapshot records SIGSEGV with `si_code=1`
(`SEGV_MAPERR`) and `si_addr=0x144f6a24`, equal to the FPGA load base. This
address lies outside the recorded backing object and outside every load mapping
in the core. Other captured FPGA registers are `a3=1`, `s8=9`, `s5=5`, and
`s0=0xf1910`; QEMU comparison values for those registers were not supplied.

**This supports outcome 2: earlier execution-state divergence, not a false
fault on the recorded valid QEMU addresses.** The record compares QEMU's first
hit with FPGA's failing hit; it does not identify the first divergent dynamic
instruction or establish whether the originating problem is hardware, kernel,
or compiler behavior. No further localization run was authorized or launched.

The private core independently corroborates all eight requested scalar
registers and the vector header (`VL=1`, `VTYPE=0x17`, `VSTART=0`, `VLENB=32`).
The core's signal note has `si_code=-6` because libgfortran re-raised SIGSEGV.
The original signal address above comes from `PTRACE_GETSIGINFO` before signal
delivery; interpreting the re-raised note as an original memory address would
be incorrect.

The VLEN-256 full/tail probe, manager exit, simulation completion and shutdown
passed. SPEC correctness did not pass; this is exclusively a diagnostic and
must not become a performance sample. The worker was verified idle. All raw
core/memory, register snapshots, UART and debugger logs remain private under
`/home/ubuntu/cs262_compiler/saturn-spec-lane/diagnostic-009/`.
See `saturn-role2-diagnostic-replacement-receipt.json` for sanitized hashes and
selected diagnostic values. No additional retry or role 3 was started.

Earlier analysis and the failed first diagnostic checkpoint follow.

## Reproduced hardware failure

Three fresh executions of the frozen role-2 ELF
`933c5062989468d8eba30c72a08dadb2e15bf39dfffff2532f5f2fed5cada541`
passed the VLEN-256 probe and then terminated with SIGSEGV at PC `0x11e80`.
The instruction is:

```text
vlse32.v v0,(a4),s1
```

Every result was correctly rejected because `s.txt` was empty. Repeating the
same hardware run again cannot distinguish a compiler-address problem from a
Saturn fault-checking problem.

## Frozen-ELF QEMU register evidence

The exact unchanged ELF and official test input were rerun under the pinned
QEMU at VLEN 256. RISC-V GDB stopped before the first execution of `0x11e80`:

```text
a4    = 0x0f1924
s1    = 0x000144
t2    = 9
vl    = 4
vtype = 0x17 (e32, mf2)
vstart = 0
```

The four element addresses are `0xf1924`, `0xf1a68`, `0xf1bac`, and
`0xf1cf0`. The ELF symbol table defines `__brute_force_MOD_block` at `0xf1910`
with size 2,916 bytes, ending at `0xf2474`. Thus every address is naturally
aligned, remains inside the same backing object, and remains inside the same
4-KiB page. QEMU can read the first and last words and later completes with the
exact expected output.

This does not yet prove the FPGA has the same scalar-register values: an
earlier vector misexecution could change the path or loop indices. It does
show that the frozen compiler sequence has an architecturally valid execution
and gives exact values against which to compare a hardware fault core.

Saturn documents support for indexed and strided vector memory operations and
routes potentially arbitrary-page strided operations through its iterative
fault checker. See the upstream
[frontend documentation](https://github.com/ucb-bar/saturn-vectors/blob/master/docs/tex/frontend.tex).
The selected `dfe75de...` revision already includes its fractional-LMUL
pipelined-fault-check fix, so merely moving to that known fix is not an option.

## Next discriminating test

Do not change the role-2 ELF or retry it blindly. Prepare one explicitly
diagnostic fresh guest that enables a private core dump for the same unchanged
invocation. Preserve and collect the core even though correctness collection
rejects the sample. Inspect only scalar registers and signal metadata at the
fault:

- `pc`, `a4`, `s1`, `t2`, `a3`, `s8`, `s5`, `s0`;
- `si_addr`, if present;
- vector `vl`, `vtype`, and `vstart`, if the kernel core format exposes them.

If the hardware values match the QEMU values above, the evidence points to a
false Saturn memory fault for a valid single-page `vlse32.v` with fractional
LMUL. If they differ, locate the first earlier vector-dependent divergence
before changing compiler targeting. This diagnostic is not a performance
sample and must not replace frozen role 2.

## Manager diagnostic checkpoint: boot failed before workload

The single authorized diagnostic hardware attempt used an unchanged frozen
role-2 ELF and official input bundle. Its admitted guest enabled core dumps
and carried a separate ptrace launcher to preserve the first signal's scalar,
vector and siginfo state before libgfortran could re-raise it. No protected
component was rebuilt. The adapter and lane tests passed (57 focused tests).

This attempt panicked in Linux during `rcS`, before the workload runner or
role-2 executable started: illegal instruction at `kobject_get+0x30/0x78`
(`epc=0xffffffff8078cc5a`, `badaddr=0x60e20207`). The private worker image has no
result directory. No role-2 core or first-fault snapshot was generated, so
**neither register-comparison hypothesis has been determined**. This kernel
trap must not be reported as the role-2 userspace vector fault.

The matching failed simulation was stopped, raw UART/manager evidence was
preserved privately, and post-stop preflight verified the worker idle. No
replacement boot was launched because the operator authorized one diagnostic
attempt. The accepted kernel configuration includes `CONFIG_COREDUMP=y` and
its source has an `NT_RISCV_VECTOR` regset; the failure does not establish that
a kernel rebuild is required or that this format cannot expose the state.

See `saturn-role2-diagnostic-receipt.json` for sanitized hashes and outcome.
The private stage is under
`/home/ubuntu/cs262_compiler/saturn-spec-lane/staging/role2-diagnostic-008/`.
The capture launcher is ready for a separately authorized replacement attempt;
do not change role 2 or treat this diagnostic as performance.

The capture design accounts for GCC 15.1's
[libgfortran signal handler](https://raw.githubusercontent.com/gcc-mirror/gcc/releases/gcc-15.1.0/libgfortran/runtime/compile_options.c),
which prints a backtrace and then re-raises the signal. Its eventual core may
therefore carry re-raise registers/siginfo; the pre-delivery ptrace snapshot is
the authoritative first-fault state. Vector `vstart` at a fault may also differ
from QEMU's pre-instruction zero after partial progress; compare base, stride,
VL and VTYPE before interpreting that difference as earlier divergence.
