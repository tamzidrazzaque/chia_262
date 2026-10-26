# SPEC CPU2017 tuning experiment status (2026-10-26)

This document records an internal research experiment, **not** an official SPEC result or a BOOM SPEC performance claim. No licensed SPEC media, inputs, sources, binaries, or disassembly are stored in this repository.

## Completed

- CPU2017 1.1.9 installed privately from the lab ISO at `/nscratch/spec/2017/cpu2017-1.1.9.iso` (SHA-256 `9b67bdf77cf749b96520a4ee4f1acb3cc5aeb87c89f0dbf3f0bc7f718ed1de09`). The installation and logs are under `/home/eecs/trazzaque/spec2017-research/`, whose parent is mode 0700. The installer passed its checks.
- `505.mcf_r`, `531.deepsjeng_r`, and `557.xz_r` were each built three times for RISC-V GNU/Linux with GCC 15.1.0: `-O3 -march=rv64gc -mabi=lp64d -static -mtune={rocket,generic-ooo,xiangshan-nanhu}`. The selected GCC executable's SHA-256 is `e46d71073c10417353a0718bff6bfadb818757b887da2622d353926a26700b0c`. `make.out` in each private SPEC build directory confirms the flags. There is no genuine BOOM-specific tune in that compiler.
- All nine combinations executed the SPEC `test` input under a privately extracted `qemu-riscv64-static` and reported `Success <benchmark> base test` from SPEC's correctness checks. This is QEMU user-mode execution, not a FireMarshal Linux guest or BOOM.
- `spec_asm_compare.py` examined all nested object files using the cross-`nm` and cross-`objdump`. It emits only function names and opcode/size aggregates. Compared with Rocket, generic/Xiangshan changed 31/32 mcf functions, 74/93 deepsjeng functions, and 229/266 xz functions. The biggest candidate effects: mcf selects hardware divide/remainder under out-of-order tunes, mcf/deepsjeng sometimes replace shift/add with multiply, and xz's SHA-256 routine has hundreds more loads/stores under out-of-order tunes. These are static observations, not measured BOOM effects.
- A real local CHIA `@ChiaFunction`/Ray job, `chia_spec_local.py`, serialized the three mcf tune builds and validations and wrote a three-result JSON summary. It did **not** use Docker or `chia up`.
- The earlier bare-metal Small BOOM microbenchmarks showed roughly 3.1–3.3% faster integer-mix and 8.4% faster Xiangshan branch-heavy cases, while identical SAXPY/dot hot loops tied. Those results do not predict SPEC behavior. See `README.md` and the local research report in `/scratch/trazzaque/SLICE/cost-model-out/` when available.

## Reproduce or extend on the existing private installation

The private paths below must be checked on each host. Do not copy licensed files into the repository or a public image.

```sh
export SPEC_DIR=/home/eecs/trazzaque/spec2017-research/install
export GCC_ROOT=/home/eecs/trazzaque/spec2017-research/toolchain
export SPECKLE=/scratch/trazzaque/SLICE/chipyard-boom-cost/software/spec2017/speckle
export QEMU=/home/eecs/trazzaque/spec2017-research/qemu/root/usr/bin/qemu-riscv64-static
export OUT=/home/eecs/trazzaque/spec2017-research/results
python examples/boom_cost_model/spec_cpu2017_local.py --spec-dir "$SPEC_DIR" --gcc-root "$GCC_ROOT" --speckle "$SPECKLE" --qemu "$QEMU" --out "$OUT" --benchmark 505.mcf_r --size test --tune rocket --action build
python examples/boom_cost_model/spec_cpu2017_local.py --spec-dir "$SPEC_DIR" --gcc-root "$GCC_ROOT" --speckle "$SPECKLE" --qemu "$QEMU" --out "$OUT" --benchmark 505.mcf_r --size test --tune rocket --action validate
python examples/boom_cost_model/spec_asm_compare.py --spec-dir "$SPEC_DIR" --gcc-root "$GCC_ROOT" --benchmark 505.mcf_r --out "$OUT/505.mcf_r-asm-summary.json"
```

The comparator needs all three tune builds. A standalone local CHIA run, with CHIA's Python/Ray environment active, is:

```sh
python examples/boom_cost_model/chia_spec_local.py --spec-dir "$SPEC_DIR" --gcc-root "$GCC_ROOT" --speckle "$SPECKLE" --qemu "$QEMU" --out "$OUT" --benchmark 505.mcf_r --size test
```

Per-run `*-build.log`, `*-validate.log`, and JSON metadata, plus `*-asm-summary.json`, reside privately in `$OUT`. The JSON records compiler/config/QEMU hashes. QEMU wall time is not BOOM cycles or a valid tune ranking. The scripts' tests run with `python -m unittest discover -s examples/boom_cost_model/tests -q` in CHIA's environment.

## What remains

1. Access to `a3.millennium.berkeley.edu` from the prior session failed at SSH public-key authentication, so Docker group membership, `docker ps`, `docker info`, shared paths, and resources there were **not** verified. A new SSH login is also needed after group changes. Current `chia/cluster/docker.py` uses host networking; before any Docker-backed CHIA cluster, verify that every listening service is bound to `127.0.0.1`, or change the network/service configuration to meet the lab's rule. Do not assume `-p 127.0.0.1:...` constrains `--net=host`.
2. The isolated Chipyard checkout is at `bcb612918bb964a0dad33a26a1921c161eb598d0`, nested Speckle at `e43e0a6c1a54da6fe74d9ca31f82f974f87327c0`, FireMarshal at `21119e5ce922ff9302f0bc9d2d7349c77f7ac064`. FireMarshal has **not** been built/launched. Try one `spec17-intrate-test-500.json` image first, inspect launch and post-run output, and do not blindly update submodules.
3. The existing Small BOOM Verilator executable is a bare-metal HTIF simulator, not a Linux SPEC target. On-prem U250 hardware and XDMA were observed, but no matching BOOM bitstream/runtime was identified. Establish one Linux-capable BOOM FireSim configuration and reuse it for all tunes before claiming SPEC performance. Measure benchmark-only cycles and retired instructions with repetitions; compute IPC only if both counters exist. No SPEC BOOM cycles/IPC have yet been obtained.
4. Prioritize mcf's divide path, deepsjeng's multiply path, and xz's expanded SHA-256 load/store path for profiles, GCC dumps, and same-BOOM measurement. Static instruction count alone is insufficient: serialized multiply/divide latency and memory pressure can reverse a code-size win.

Do not start AWS or incur cloud cost without explicit user approval. Keep test and reference inputs clearly distinguished and keep every tune's ISA, ABI, compiler version, input, BOOM configuration, and measurement boundaries identical.
