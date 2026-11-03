# Source-derived Rocket notes

These facts come from the pinned source used to reconstruct the driver. They
are not measured latency/throughput claims or independent recovery of the
FPGA builder's complete original source archive.

Chipyard `19a07f6b8d4d1db81f5561d9aeceb2cdc43407fe` selects
`WithNHugeCores(1)` for `RocketConfig`. Rocket Chip revision
`55bcad0f59436de98ea510334121de8546b9e9d7`,
`src/main/scala/rocket/Configs.scala`, defines that configuration with:

- One Rocket tile, not a BOOM issue queue/ROB model.
- Integer multiply unroll 8, multiply early-out enabled and divide early-out
  enabled. These parameters do not imply one fixed latency for every operand.
- Blocking D-cache (`nMSHRs=0`), 64 sets and 8 ways. Confirm block size and all
  applied mixins before translating these into cache capacity claims.
- Scalar Zba/Zbb/Zbs enabled in this source configuration. The initial compiler
  experiment deliberately uses fixed `rv64imafdc/lp64d` for compatibility with
  the handoff. Any later scalar bit-manipulation ISA experiment needs its own
  baseline; do not mix it with cost-only changes.
- An FPU is configured, but no vector unit is selected by this target. Scalar
  floating point and integer-only applications should still be reported separately.

The FireSim target uses `WithFireSimHighPerfConfigTweaks` and `BaseF2Config`.
It differs from MegaBOOM's test-chip clocking and FRFCFS/LLC configuration. Keep
per-target baselines, runtime settings and physical-worker labels separate.
Hardware guest CPU/ISA evidence and real application correctness must be checked
before accepting an FPGA application measurement.

## Application rebuild reproducibility

The initial full zstd executable comparison exposed embedded absolute build
paths, even though the unchanged compiler's smoke assembly checks passed.
Compiling `lib/compress/zstd_compress.c` from the same path produced identical
assembly with the original compiler and the immutable unchanged rebuild.

`prepare_zstd.py` now adds `-ffile-prefix-map=<build-dir>=/zstd-src` to both builds.
After that change, the **entire linked scalar RISC-V zstd executable** was
byte-identical for the original installed compiler and the unchanged rebuilt
compiler, with SHA-256:

`7f52374b3d691b32aea689d726b0d048c4bd1b0b648e7efe9774b909cb549084`

The private comparison artifacts are `zstd-original-002` and
`zstd-rebuilt-002` in the build worker. Earlier `-001` application builds are
retained as diagnostic evidence; do not use their path-contaminated binaries
as the baseline for the tuning campaign. Fixed source-path mapping is part of
all future baseline and candidate flags, not an optimization credited to a cost
model. The original installed compiler is still the performance control.
