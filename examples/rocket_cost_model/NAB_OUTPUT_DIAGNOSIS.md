# NAB baseline output diagnosis

**Current status, 2026-11-23: bounded diagnosis complete; cause unresolved.** The initial stock-vector
pilot passed official numerical validation, but a subsequent fresh run of the
same frozen executable failed the installed official comparator. Five values
differed; four exceeded 1% and the largest relative error was about 7.68%.
This later failure is not an exact-hash policy problem. Three additional local
QEMU executions of that same ELF produced the exact pinned reference hash.
Neither observation identifies the hardware/software component responsible.

The separate kernel panic occurs before NAB starts and remains unresolved.
See [the boot audit](BOOT_CAUSAL_AUDIT.md). This experiment diagnoses output
repeatability after a successful boot; it does not address or explain the boot
panic.

## MCF comparison and bounded repeatability test

The frozen MCF and NAB role-2 bundles use the same GCC 15.1 build and revision,
compiler digest, target flags, RISC-V architecture, VLEN 256, and unchanged SPEC
sources. Their QEMU validation passed. The workloads and resulting ELFs differ.
Static disassembly of MCF role 2 contains 163 RVV instructions and no vector
floating-point instructions. NAB role 2 contains 3,569 RVV instructions,
including 337 vector floating-point instructions. MCF's successful exact-output
run therefore does not exercise the vector floating-point operations that NAB
uses. These are static counts; they do not establish dynamic coverage or prove
that vector FP causes NAB's mismatches. The same compiler and target settings
also mean the result is not explained by a different compiler setup.

The diagnostic-only `nab_repeat.c` stage completed on the NAB F2 worker and
dispatched the unchanged role-2 ELF twice in a single guest boot. Each
execution got a clean copy of the same inputs and exact frozen invocation,
ordinary ASLR and scheduling, separate stdout/stderr/status files, and an
executable mapping capture. Both exits were zero, both mappings differed, and
both 626-byte outputs matched the pinned reference hash exactly. The installed
official `specdiff` passed both outputs (`--reltol 0.01 --skipreltol 2`). This
shows that within-boot process/address-layout variation did not reproduce the
earlier output failure in this pair. It does not rule out variation between
boots or establish an RTL/software root cause. No cycles were collected and
this is not a performance sample.

The historical passing and failing role-2 runs used the same physical NAB
worker, role-2 bundle
`9aa5d0dcf54c0e4ba05b50bd22f7cd80de9812386cac55f65a5dbcf10575dde9`, platform
digest, AGFI, driver, VLEN, and boot binary. Their compiler manifests and
inputs match, and the stage overlays differ only in run identity records; the
runner scripts are identical after removing that identity line. The passing
output hash was `05bc2982e5efb0f9b91f23e5a52dd8636991d0f7958f8d1babf498f5b10cb8a1`
and passed official comparison. The failing output hash was
`0df3c794a823b0b87e6c5ecc0a81051b08f78b84b039494e12e506deacd4052c`; official
comparison returned failure. Thus worker identity, compiler revision, role-2
ELF, inputs, or compiler flags alone do not explain the differing outcomes.

No cycle comparison or performance claim is valid for this diagnostic. Its
protocol is rejected by performance collection, and all original baseline
receipts remain unchanged.

The first launch attempts were rejected before hardware dispatch: the
repository virtualenv cannot import FireSim's `fabric`, and each stage needs
its own successful `infrasetup` receipt. A later guest boot exposed another
missing admission check: its helper was an x86-64 host binary. The guest
recorded exit 126 and collection failure (`Exec format error`); FireSim's
zero exit did not mean the workload ran. NAB was not launched in that task.
The local `staging.py` now checks that a NAB helper is a static ELF64 RISC-V
binary before image construction, with a regression test for rejecting host
ELFs. The manager copy did not yet have that new check when it built stage 004;
the helper and embedded image copy were independently verified as identical,
static RV64GC binaries. These failed attempts are retained and excluded from
workload evidence.

## Initial pilot and validator repair (historical)

The first stock-vector NAB pilot completed successfully on Saturn. Its admission
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

The recovered initial baseline gate passed and launched the same continuous NAB
runner, with four queued profiles followed by feedback-based GPT-5.6 Sol/high
proposals. The deployed suite passed 145 tests plus 22 subtests.
Later failures stopped that campaign; it is not currently running.
