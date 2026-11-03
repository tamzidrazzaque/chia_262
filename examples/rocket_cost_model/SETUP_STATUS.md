# Non-SPEC setup status

This file records setup evidence, not benchmark speedups. SPEC is paused.
Private binaries, generated bridge files, raw logs and compiler snapshots stay
outside Git and are backed up separately.

## Completed

- Dedicated CHIA Python environment and target-specific rejection tests.
- Existing owner-authorized F2 worker prepared with Docker, QEMU user-mode
  support and pinned FPGA SDK `80b34d3c25aff03353c0b4f2d304bb6067a5011d`.
  SDK setup passed. No AWS security-group or SSH-daemon policies were changed.
- CHIA chisel-build image staged and pinned to digest
  `sha256:0a8b31fb15c9e9ee815733fa43f2e88a9c0dcd9f026e0b616ff4337e912d7647`.
  Its original sources were newer than the image under test. A disposable,
  resource-bounded container was restored to the exact Chipyard/FireSim/Rocket
  pins in `image-discovery.json`; the inherited compiled tapeout cache was
  invalidated before compiling.
- Rocket elaboration, Golden Gate generation and driver compilation completed
  successfully. Generated evidence covers 58 files. Original driver executable
  SHA-256: `35c1569fb04dcdfdbf75797578010bf4aa750370b91a41d613d85030cc24d8f0`.
  Driver/shared-library bundle and source/build evidence were saved on the worker
  and backed up locally at `../driver-bundle-001`.
- Public single-core Rocket AGFI `agfi-033a86c6e5d006fc8` loaded into a confirmed
  clear, idle slot. The management tools report the expected loaded image,
  shell `0x10212415` and PCI device `0xf002`.
- The rebuilt driver attached to BAR0/BAR4 and exited successfully with
  `+check-fingerprint`, reading `0x46697265`. This is FireSim's generic presence
  fingerprint, **not a unique hash of the Rocket design or a workload test**.
  Full guest/application validation remains a separate acceptance gate.
- The original installed GCC hash equals the handoff baseline. An immutable,
  unchanged GCC snapshot was rebuilt without overwriting the installed compiler.
  Snapshot ID:
  `1ade3ffa4b7a64471e8e1329254c2faefdb1302e85774d4bb8ce8a7c36d56998`.
  C, C++ and Fortran smoke assembly matched the original compiler, and all
  three static-link checks passed. Compiler source archive and backend hashes
  were checked. The rebuild is private at `/home/ray/rocket-gcc` in the worker's
  disposable build container.
- Full application rebuild parity also passed after removing absolute build
  paths with a fixed file-prefix map. Original and unchanged rebuilt zstd CLIs
  are byte-identical; see `TARGET_NOTES.md`. Earlier noncanonical binaries are
  diagnostic artifacts, not the campaign baseline.
- The real zstd CLI builds and native/user-QEMU round trips pass; see `ZSTD.md`.
  Workload overlay preparation, full runtime/sample cache identities and strict
  output collection are implemented. Search and confirmation keys are separate.

## Linux guest validation completed

The custom FireMarshal Linux base built successfully with Bash and coreutils.
The canonical zstd overlay was composed into `zstd-image-001`, with image naming
bound to the application, input, runner, base image, boot binary and distro
fragment hashes. The full Linux guest then booted under QEMU with networking
disabled, completed compression/decompression with exact decoded bytes, collected
all outputs successfully and powered down. QEMU timings are functional evidence
only; they are not Rocket performance measurements.

The guest artifacts currently reside in worker container `rocket-guest-build`:

- `/home/ray/rocket-artifacts/zstd-image-001`
- `/home/ray/rocket-artifacts/zstd-qemu-guest-001/correctness.json`
- `/home/ray/rocket-images/rocket-zstd-base-bash-coreutils-v1`

The pinned build snapshot is `rocket-pinned-build:source-19a07f6`. The original
build container is `rocket-driver-build`. These private artifacts are not in Git;
copy the guest/base outputs to persistent host storage before removing containers.

## Resume here

1. Persist the guest/base artifacts outside their container. The driver bundle
   and compiler snapshot already have separate backups.
2. Complete and retain the source/manifest review against public AWS metadata.
   A locally reviewed manifest was prepared separately; the original unverified
   manifest remains unchanged. Generic FireSim presence is not unique design
   verification, and the original FPGA-builder source archive was not recovered.
3. Stage a dedicated runtime container with the pinned sources and SDK, host PID
   namespace, host networking and the owned host mount. Use the guarded
   `run_zstd_local_fpga.py` adapter. Its first full FPGA application run has
   **not yet been executed**; this adapter remains integration-unvalidated.
4. Collect an original-compiler Rocket application baseline before any candidate
   selection or speedup claim. `build_candidate.py` can build bounded proposals,
   but does not implement or run an adaptive search.

The existing SPEC-specific `fpga_stage` hard-codes the earlier campaign SDK and
must not be used as the Rocket execution adapter. SPEC remains paused. This
checkpoint includes no FPGA application timings and no adaptive tuning campaign.
