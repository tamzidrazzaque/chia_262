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
