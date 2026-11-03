# Rocket agent handoff

## Start here

Continue branch `research/rocket-scalar-cost-model` in
`examples/rocket_cost_model/`. The implementation checkpoint is `661519a`.
Read this document, [the resume runbook](ROCKET_RUNBOOK.md),
[setup status](../examples/rocket_cost_model/SETUP_STATUS.md), and repository
`AGENTS.md` before changing code or launching anything.

This handoff and SETUP_STATUS describe the latest verified state. PLAN.md,
READINESS.md and ZSTD.md include historical planning/checkpoint statements;
statements that the driver, compiler or Linux guest are still unbuilt are stale.
The original technique reference is branch
`handoff/compiler-cost-models-20261030`, based here at `fd6bff3`.

## Objective and user decisions

Adapt the other branch's iterative measured compiler cost-model technique to
scalar Rocket applications. The teammate mainly owns MegaBOOM. Keep both targets'
compiler snapshots, hardware guards, measurement labels and conclusions separate.

The user wants real applications, not a synthetic-kernel performance campaign.
SPEC is paused while the user investigates licensed access. Do not download
unauthorized SPEC copies, wait for SPEC to do useful work, or replace real target
measurements with QEMU timings. Start with the full upstream zstd CLI.
The user authorized preparing and using one of the existing F2 workers and
publishing this research branch. No adaptive tuning campaign has run.

## Verified progress

- Exact public single-core Rocket image found and loaded; matching pinned-source
  driver rebuilt after invalidating inherited compiled caches.
- Driver BAR attachment and generic FireSim fingerprint probe passed. This
  fingerprint is not a unique hardware design hash.
- Original GCC baseline identity verified. Immutable unchanged GCC rebuild passed
  C/C++/Fortran code-generation and static-link checks.
- Full original/rebuilt zstd executables became byte-identical after applying
  the same fixed source-path map to both. Preserve that flag for candidates.
- Custom Bash/coreutils Linux base and canonical zstd image built successfully.
- Full Linux QEMU boot, training compression/decompression, exact-byte validation,
  successful collection and guest shutdown passed with networking disabled.
- Guarded local FPGA adapter and bounded compiler proposal builder are implemented.
  The FPGA adapter has not passed its first hardware integration run.
- Relevant Rocket, BOOM and shared-code regression selection: **164 passed**.

**No full FPGA application run, baseline variability estimate, candidate ranking,
confirmed speedup or adaptive controller execution is available.**

## Hardware and compiler identity

| Item | Value |
| --- | --- |
| AGFI | `agfi-033a86c6e5d006fc8` |
| AFI | `afi-065352b4754b46048` |
| Shell | `0x10212415` |
| Chipyard | `19a07f6b8d4d1db81f5561d9aeceb2cdc43407fe` |
| FireSim | `b7927ea504c501194eaec3e993c415f2270170f8` |
| Rocket | `55bcad0f59436de98ea510334121de8546b9e9d7` |
| AWS FPGA SDK | `80b34d3c25aff03353c0b4f2d304bb6067a5011d` |
| GCC | 13.2.0, pinned source/baseline verified by prepare_compiler.py |
| ISA / ABI | `rv64imafdc` / `lp64d`, Rocket tune, loop/SLP vectorization disabled |

Quintuplet:
`f2-firesim-FireSim-WithDefaultFireSimBridges_WithFireSimHighPerfConfigTweaks_chipyard.RocketConfig-BaseF2Config`.

Do not use BOOM's SPEC `fpga_stage`: it pins a different SDK. Read
`TARGET_NOTES.md` for source-derived Rocket parameters and their limits.
The source reconstruction was compared with public image metadata; the original
FPGA builder's complete source archive was not recovered. Preserve this limitation
and the original unverified manifest when finishing the private manifest review.

## Code map

| Path | Purpose |
| --- | --- |
| `chia/chipyard/rocket_target.py` | Exact hardware, driver/evidence hash and source-verification guards |
| `prepare_compiler.py` | Pinned compiler setup and unchanged-rebuild gate |
| `build_candidate.py` | Bounded complete cost-table proposal; hypothesis/falsifier required |
| `prepare_zstd.py` | Real upstream CLI, deterministic disjoint corpora, fixed flags |
| `prepare_zstd_image.py`, `zstd_image_job.py` | Hash-bound overlay, Linux base and image composition |
| `validate_zstd_guest.py` | Full QEMU validation and safe archive handling |
| `run_zstd.sh`, `zstd_results.py` | Application protocol and strict correctness/identity collection |
| `run_zstd_local_fpga.py` | Single-worker locked local FireSim adapter; first integration run pending |
| `experiment.py` | Rocket-specific adaptation of inherited application stages |

`chia/trace/status.py` avoids initializing Ray just to report status.
`FireSimManagerNode(watch_status=False)` supports the explicit local adapter;
existing callers retain the original default status watch.

## Research sequence after the first FPGA pass

1. Obtain three independent original-compiler pilot samples and wall-time data.
2. Inspect baseline hot code and select one isolated bounded scalar-cost edit.
3. Build immutable candidate; validate scalar ELF, correctness and changed code.
   Deduplicate identical executables before spending target time.
4. Pair candidate measurements with this physical worker's baseline; preserve
   compiler/input/runner/rootfs/boot/runtime/driver/phase/sample identities.
5. Implement finite proposal/attempt/time budgets, atomic resume records and
   stop/drain handling before running an adaptive controller.
6. Freeze training selection before independent confirmation and held-out inputs.
   Retain the baseline if the evidence does not support improvement.

The plan proposes at most six distinct candidates and twelve proposal attempts;
freeze actual wall-time and regression thresholds after measuring the pilot.
Do not claim this budget or runtime has already been validated on Rocket.

## Reporting and publication

Publish sanitized code, identities, validation outcomes and research limitations.
Keep credentials, licensed inputs, generated binaries/rootfs, raw logs and private
manifests outside Git. Do not merge, release, sign a human DCO, change access
controls or send teammate messages without the applicable authorization.
Use the repository-local Corey Yu identity; push using the user's coreydipsy
account. Preserve the existing global GitHub account selection after any switch.
