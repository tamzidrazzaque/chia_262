# Real zstd application pilot

The first application is the full upstream zstd command-line program, pinned
to v1.5.7 commit `f8745da6ff1ad1e7bab384bd1f9d742439278e99`.
Upstream source: https://github.com/facebook/zstd/releases/tag/v1.5.7
The upstream BSD license is retained in the exported source. No third-party
source, corpora, executables or generated results are committed here.

## Preparation

From the repository root, with an existing official source checkout:

```bash
../.venv/bin/python -m examples.rocket_cost_model.prepare_zstd \
  --source /absolute/path/to/zstd-source \
  --output /absolute/path/to/new-private-run \
  --gcc /absolute/path/to/riscv64-unknown-linux-gnu-gcc
```

The command exports committed source bytes and builds the native and static
RISC-V Linux CLIs from identical source. It limits build parallelism to four,
disables optional compression-library integrations, legacy formats and threading,
and disables loop/SLP vectorization. The target uses `rv64imafdc/lp64d` and
Rocket tuning. The original compiler remains untouched. Inspect final ELF
attributes and disassembly before admission; flags alone are insufficient.
Build manifests retain compiler/source/binary identities and exact commands.
The output directory must be new; changed configurations cannot overwrite it.

Two deterministic tar corpora contain actual application source files:
`train.tar` contains compression-module C/header files; `holdout.tar` contains
decompression-module C/header files. These are real source-code compression
inputs rather than random/repeated generated data. They are a small source-code
pilot, not a representative general-purpose compression benchmark suite.
Training and holdout files are disjoint. Do not use held-out performance to
choose compiler settings. Add diverse real datasets later with explicit licenses,
hashes and separate input identities before making broader performance claims.

## Application protocol

`run_zstd.sh BINARY INPUT_TAR NEW_OUTPUT_DIR` runs a warmup round trip, times
level-3 compression and decompression separately with Bash's elapsed
wall-time reporting, and requires byte-for-byte equality with the original input.
Bash `time` reports elapsed wall time; it is not an instruction counter and may
reflect target OS/I/O overhead. It must be interpreted as guest application
elapsed time only when run on the verified Rocket guest. Save raw times, input
and executable hashes, return status and output hashes. An unsuccessful
application never produces an accepted correctness marker. Completed output
sets cannot be overwritten. The guest must supply Bash, realpath, sha256sum and
cmp; verify these in the chosen Linux rootfs. A timer reading of zero or a
missing output/collection status must be rejected by the future collector.

The runner includes process startup and file I/O, which are part of this
application protocol. Keep filesystem, boot state, warmup, input sizes and
measurement order fixed across baseline/candidate. Copy these files into a
FireMarshal Linux image and collect the results through FireSim. Do not interpret
native or QEMU timing as Rocket performance. Multiple confirmations require new
output directories and independent campaign-phase/sample identities.

## Completed functional checks

Prepared artifacts outside Git at `../zstd-pilot-001`:

- Full native CLI and static RISC-V CLI built successfully.
- Training corpus: 1,044,480 bytes; held-out corpus: 317,440 bytes.
- Native training round trip passed using the saved application protocol.
- RISC-V QEMU training round trip passed on the selected F2 host; source and
  recovered bytes both hashed to
  `650c9a7263d5394f75a3923916ea9880f39bb916a07115096fce9da78304adc6`.
- Target ELF attributes list `rv64i/m/a/f/d/c/zicsr/zmmul`, without V.
- Workload/target software checks: 15 passed. These test byte preservation,
  failure recording, overwrite rejection and hardware identity acceptance.

No Rocket guest performance measurement has occurred. The existing F2 host is
running, Docker and QEMU user-mode support were installed there, and the CHIA
chisel-build image is being staged. Its actual source revisions and dependencies
must be inspected after download. A matching driver/bridge build and Linux
image are still required. Existing MegaBOOM SPEC stages cannot be used directly
for this non-SPEC application: image composition, a zstd collector and a bounded
Rocket campaign entry point remain implementation work. SPEC access is paused.

## Setup commands added after the initial pilot

- `prepare_zstd_image.py`: create the hash-bound application overlay.
- `zstd_image_job.py`: build/reuse an explicitly provisioned Linux base and
  compose a workload in a privileged FireMarshal worker.
- `validate_zstd_guest.py`: full-guest QEMU boot, read-only result collection
  and correctness validation.
- `zstd_results.py`: reject malformed/incomplete results and keep full runtime,
  worker, phase and repeat identities distinct.
- `prepare_compiler.py`: native pinned GCC setup and unchanged-rebuild gate.
- `bundle_driver.py`: driver/shared-library packaging and private source evidence,
  producing an unverified manifest until provenance review.

`SETUP_STATUS.md` tracks actual setup outcomes and limitations.
