# NAB baseline output diagnosis

The stock-vector NAB pilot completed successfully on Saturn. Its admission
failure came from applying an exact-output hash policy to a floating-point
workload whose official SPEC comparator permits numerical tolerance.

The installed `644.nab_s/Spec/object.pm` and generated comparison command
specify relative tolerance `0.01` and `skipreltol=2`. Running the installed
official `specperl`/`specdiff` on the preserved FPGA output against the official
`544.nab_r/data/test/output/hkrdenq.out` returned zero, with the explicit
`specdiff run completed` message and no stderr. The same command passed on the
bundle reference. The `-m` option was omitted to avoid accepting incomplete
output through missing-line relaxation.

The official reference SHA-256 is
`2d580a95e2e596f2e06485149e9d91880bf47ded5a5495a366a80d4cea2a9afd`;
the preserved FPGA output SHA-256 is
`05bc2982e5efb0f9b91f23e5a52dd8636991d0f7958f8d1babf498f5b10cb8a1`.
Both files have 626 bytes, 26 lines and 17 numeric tokens. Two values differ;
maximum relative difference is approximately `0.00010593445` (0.010593445%).
Guest and collection statuses are both zero. These observations establish
that this run satisfies official output validation, not why the numerical
values differ between platforms or that every Saturn instruction is correct.

The collector now accepts a conservative subset of the official comparison
for this exact benchmark, test size, output filename and pinned reference.
It requires identical text structure, unchanged integer values, finite
numbers, and every floating-point value within the 1% relative limit. It
permits no skipped differences. Other workloads retain exact comparison.
Receipts record the validator policy and both output hashes. Licensed output,
installed SPEC comparison sources and raw evidence remain private.

Recovery revalidated the preserved completed run through the full collector,
including image hashes, executable identity, VLEN probe, guest exit status,
clean shutdown, task identity and output policy. Original failed-attempt
evidence was preserved; no hardware rerun was needed. The recovered vector
receipt reports 37,665,524,822 whole-boot cycles, versus the scalar pilot's
36,937,795,127. These individual pilots are qualification evidence, not a
paired performance conclusion.

The recovered baseline gate passed and launched the same continuous NAB
runner, with four queued profiles followed by feedback-based GPT-5.6 Sol/high
proposals. The deployed suite passed 145 tests plus 22 subtests.
