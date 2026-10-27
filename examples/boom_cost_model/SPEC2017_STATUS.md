# SPEC CPU2017 tuning experiment status (2026-10-26)

This document records an internal research experiment, **not** an official SPEC result or a BOOM SPEC performance claim. No licensed SPEC media, inputs, sources, binaries, or disassembly are stored in this repository.

## a3 continuation

Checked on `a3.millennium.berkeley.edu` after a fresh SSH login. Docker group membership is effective. The private SPEC tree and GCC 15.1.0 binary (`e46d7107…`) are intact. `/scratch/trazzaque/SLICE` and the old Chipyard checkout were gone; pinned FireMarshal `21119e5c`, spec2017-workload `83e3311`, and speckle `e43e0a6` were cloned again under `/scratch/trazzaque/SLICE`. No Xilinx device or XDMA node is present, so no SPEC workload ran on BOOM.

A Docker `--net=host` CHIA job is safe here only with the loopback bind guard and a non-`127.0.0.1` loopback alias (`127.88.0.1` on this run). Ray rewrites `127.0.0.1` to the LAN address. `chia up` was not started: there is no user SSH key, and `localhost` in `known_hosts` does not match the current sshd key. The guard was taken from `origin/main` commit `0df5972` and was not merged.

That guarded Docker runtime rebuilt and validated `505.mcf_r` `test` for `rocket`, `generic-ooo`, and `xiangshan-nanhu`. SPEC reported `Success` for each. The recorded QEMU user-mode runtimes are not BOOM results. Logs: `/home/eecs/trazzaque/spec2017-research/results/a3-docker-mcf/`.

A full `lspci -nn` on 2026-10-27 shows only Intel and Matrox devices. There is no Xilinx endpoint, no `/dev/xdma`, and no FPGA sysfs node. The old Rocket UART log's bus `0000:61:00.0` is not on this machine.

FireMarshal `br-base` and `spec17-intrate-test-500` were built from the pinned commits. GCC 15 needed two portability flags in the Speckle configs, without changing benchmark source: `CXXPORTABILITY = -Wno-template-body` on `523.xalancbmk_r` in `riscv.cfg`, and `CPORTABILITY = -U_FORTIFY_SOURCE` on `502.gcc_r` in `host.cfg`. OpenSBI was built with `-std=gnu11`. Busybox `CONFIG_TC` was turned off because kernel 6.8 headers removed `TCA_CBQ_*`. `jlevel` was 4.

The guest launch used QEMU 6.2 system mode (`qemu-system-riscv64 -machine virt -smp 4 -m 16384`), not BOOM. `500.perlbench_r` test, 4 copies, all ended `All tests successful` with empty stderr. Guest `/usr/bin/time` real times were 290.75, 287.23, 288.48, and 290.53 seconds. UART ended `COMMAND_EXIT_CODE="0"`. These are QEMU functional-simulation times, not BOOM cycles. `handle-results.py` did not finish because `pandas` is not installed; the raw copy outputs are the validation. Logs: `/scratch/trazzaque/SLICE/FireMarshal/runOutput/spec17-intrate-test-500-launch-2026-10-27--11-17-16-RKPPA41SZQLA7JE1/`. The detailed note is `/scratch/trazzaque/SLICE/cost-model-out/RESEARCH_REPORT.md`.

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

1. `chia/cluster/docker.py` still uses `--net=host`. On a3, Ray rewrites `127.0.0.1` to the LAN address. The working Docker job set `CHIA_LOOPBACK_BIND_IP` to another 127/8 address and preloaded the loopback `bind` guard from `origin/main` commit `0df5972` (not merged). `chia up` was not used.
2. No SPEC workload has run on BOOM. a3 has no FPGA. The next machine needs a Linux-capable BOOM (FireSim bitstream or equivalent), the same benchmark input, and benchmark-only cycles plus retired instructions. IPC only if both counters exist. Repeat the three tunes on that one configuration. The QEMU guest above used stock Speckle `-march=rv64imafdc` with no `-mtune`; it is not the three-tune comparison.
3. Prioritize mcf's divide path, deepsjeng's generic-ooo multiply path, and xz's SHA-256 stack spills for that BOOM measurement. Static instruction count alone is insufficient.

Do not start AWS or incur cloud cost without explicit user approval. Keep test and reference inputs clearly distinguished and keep every tune's ISA, ABI, compiler version, input, BOOM configuration, and measurement boundaries identical.
