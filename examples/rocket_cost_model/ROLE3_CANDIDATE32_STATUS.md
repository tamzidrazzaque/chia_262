# Role 3.2 candidate status

Candidate `dc5068e7e5f6` changed only the Saturn vector cost model's
`unalign_load` and `unalign_store` costs from 2 to 4. The pinned GCC frontend
snapshot was built from the existing GCC 15 source and the unchanged MCF test
source/input.

Local gates passed:

- SPEC/QEMU validation passed with exact MCF output.
- The candidate ELF is distinct from role 2 (`5262ac4c...` versus
  `988ed674...`).
- Static RVV instructions increased from 163 (role 2) to 220 (candidate).
- Private Saturn intake, image construction, and image verification passed.

The F2 pilot did **not** produce a workload measurement. The worker entered a
Linux illegal-instruction panic during boot in `kobject_get`, before the guest
runner or MCF executable started. The task was stopped after the worker had
run for several hours; the worker was verified idle. Private UART evidence is
retained outside Git. No cycle result, speedup claim, or candidate acceptance
is valid for 3.2.

This candidate is therefore rejected for this run as an infrastructure/boot
failure, not as a measured performance regression. A replacement F2 attempt
requires a fresh authorization and should first reproduce the accepted baseline
boot on the same worker/image path.

## Retry diagnosis

A fresh stage/image identity was tried after stopping the first hung FireSim
process. The accepted driver hash and AGFI were reverified, and the worker was
reflashed through the normal Saturn lane. The same kernel panic reproduced at
the identical boot point (`kobject_get+0x30`, `badaddr=0x60e20207`) before the
guest runner started. This makes a stale candidate image or one-off FireSim
process failure unlikely; the retry still has no workload timing result.

The worker is idle again. Further retries require resolving or explicitly
authorizing investigation of the deterministic Saturn/Linux boot fault.

## Layout-matched retry

The original role-3 image was not packaging-equivalent to roles 1/2: it used
`inp.in`, redirected stdout to `mcf.out`, and used a different input ID. The
producer now normalizes MCF role 3 to the accepted layout (`input.in`,
`stdout.txt`, and `605-mcf-test`) while preserving the official input bytes.

The fresh layout-matched image booted through Linux and completed the F2 task
with return code 0. Collection passed exact-output validation (`status:
correct`) and clean shutdown. The private receipt reports 98.09 seconds guest
elapsed and 102,146,786,282 whole-boot simulation cycles. This is the first
valid role-3 pilot; compare it only with paired role-2 runs using the same
timing scope, and do not treat the raw whole-boot difference as a final
speedup claim yet.

## Causal qualification (2026-11-23)

The successful layout-matched run did **not** prove that filename or output-path
drift caused the earlier kernel panic. It changed the generated image as well
as the layout; no exact-image A/B replay isolated that variable. Layout matching
remains necessary for paired workload controls, but is not a demonstrated fix
for the boot fault.

Reinspection of both retained failed UARTs against the accepted kernel shows
EPC `0xffffffff8078cc5a`, two bytes into a 32-bit branch beginning at
`0xffffffff8078cc58`. NAB's later failure has the same instruction-boundary
pattern in a different function. This observation motivates controlled replay
and tracing; it does not identify which component first diverged. See
`BOOT_CAUSAL_AUDIT.md` for the current evidence and comparison protocol.
