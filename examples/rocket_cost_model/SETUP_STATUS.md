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
- The real zstd CLI builds and native/user-QEMU round trips pass; see `ZSTD.md`.
  Workload overlay preparation, full runtime/sample cache identities and strict
  output collection are implemented. Search and confirmation keys are separate.

## Linux guest and next checks

A custom FireMarshal Linux base is being built with Bash and coreutils explicitly
enabled; its packages/build tools cannot simply be assumed present in br-base.
The build uses four jobs and a two-hour timeout. The driver container has CPU
and memory limits. Inspect the saved build status/logs before resuming, rather
than starting a second copy.

When the base succeeds:

1. Persist the base image/boot binary outside the container and hash them.
2. Compose the prepared zstd overlay in a disposable privileged worker.
   `zstd_image_job.py` binds its generated name to the application, input, runner,
   base image, boot binary and distro fragment identities. It preserves failures.
3. Run `validate_zstd_guest.py` in that worker with networking disabled. Require
   complete guest power-down, exact decoded bytes, matching identities and
   successful collection. QEMU timings remain functional evidence only.
4. Complete the Rocket manifest/source review and runtime preflight; the saved
   discovery/build manifests deliberately retain `matching_source_verified=false`
   until that review. Generic FireSim presence alone must not change it to true.
5. Establish a correctly collected original-compiler Rocket application baseline
   before implementing candidate selection or asserting any speedup.

This setup has not started an adaptive tuning campaign. User-QEMU checks do not
replace a full guest boot or FPGA application run. The existing SPEC-specific
`fpga_stage` hard-codes the earlier campaign SDK and is not a suitable Rocket
execution adapter without target-specific SDK verification.
