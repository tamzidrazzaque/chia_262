# Role-2 Saturn fault analysis

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
