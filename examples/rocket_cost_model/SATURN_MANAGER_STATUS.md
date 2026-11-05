# Manager takeover status

Outcome: **driver accepted**, 2026-11-05. Hardware execution has not started.

The corrected handoff at `9c4a1a0` was pulled. Fresh AWS metadata verified the
available/public AGFI `agfi-012e92467d7d2149a`, AFI `afi-0d72fa6baed12e032`,
shell `0x10212415`, exact Saturn deploy quintuplet and FireSim `b7927ea...`.
The earlier source mismatch is resolved by the catalog/build-parent distinction.

A separate Chipyard checkout was prepared at:
`/home/ubuntu/cs262_compiler/chipyard-saturn-19a07f6`.
Its Chipyard, FireSim, Saturn, Rocket Chip and F2 SDK revisions match the handoff,
and all five source trees were clean at acceptance. Existing scalar/other
checkouts were not reset. No bitstream was rebuilt, no Saturn image programmed
and no run-farm worker launched by this takeover.

## Completed manager work

- Original pinned Conda lockfile installed in this checkout's own environment.
- Official setup resumed with `./build-setup.sh --skip-conda`; exit code 0.
  Toolchain support, Scala/FireSim precompiles, FireMarshal Linux base, CIRCT and
  repository cleanup completed.
- `managerinit --platform f2` completed only in this checkout. Existing farm
  security group was reused; email notifications left blank.
- FPGA mode, `no_net_config`, one node and the official Saturn AGFI configured.
- `firesim builddriver --runtimeconfigfile config_runtime.yaml
  --buildrecipesconfigfile config_build_recipes.yaml
  --hwdbconfigfile config_hwdb.yaml` completed with exit code 0.
- Golden Gate generated 58 files for the expected quintuplet. Their hashes and
  both generated C-header hashes are recorded in `saturn-driver-acceptance.json`.
- Driver identified as x86-64 ELF; `ldd` reported no missing libraries.
- Relevant vector tests, including the receipt hash/identity checks, passed:
  14 tests plus 4 subtests. Re-run when changing the acceptance record or roles.

Driver name: `FireSim-f2` (the handoff previously called it `FireSim`).
SHA-256: `5d3353ea8e6bf2891555da3d7b29122b1143a2e3d8c61a2a55741f1fd0bc94bd`.
Official driver bundle SHA-256:
`1b4784a9158ec170993e0bc9b59a2df2f730923664aa1bd563aebe9430634534`.

Private driver output is under:
`<Chipyard>/sims/firesim/sim/output/f2/f2-firesim-FireSim-FireSimREFV256D128RocketConfig-WithAutoILA_FRFCFS16GBQuadRankLLC4MB_BaseF2Config/`.
It contains `FireSim-f2` and the official `driver-bundle.tar.gz`.
Copies, setup scripts, full manager/build logs and raw dependency output are at
`/home/ubuntu/cs262_compiler/saturn-manager-artifacts`, outside Git.
The generated Linux base is under
`<Chipyard>/software/firemarshal/images/firechip/br-base/`; its configuration
has `CONFIG_RISCV_ISA_V=y` and default vector enablement.

## Setup compatibility notes

The initial official setup needed environment-only repairs:

1. Shared Conda's classic solver was slow; a separate checksum-verified
   Miniforge bootstrap was installed without changing shared Conda.
2. Constrain bootstrap Python to 3.10: old conda-lock failed under Python 3.15.
3. Host-glibc-driven relocking encountered a removed upstream PyPI mapping URL.
   Restore the checkout's original requirements and install its checked-in lock
   directly, then resume official setup with `--skip-conda`. Its SHA-256 is in
   the acceptance record. Do not reuse an environment from another release.
4. FireSim's setup upgraded cryptography beyond its OpenSSL dependency's range;
   restoring the original locked cryptography 40.0.2 made manager imports pass.
5. The catalog-relative makefrag path does not resolve from deploy/config_hwdb.
   Use an absolute path into this checkout, or the corrected three-parent path
   in the handoff. This changes local configuration only.
6. SDK setup moved a nested IP checkout; restore its pinned gitlink before source
   acceptance. Final source trees were clean.

## Resume at the hardware gate

`matching_source_verified` is true for this driver reconstruction. This verifies
public metadata, source pins, generated interfaces and host dependencies; the
original builder's archive was not independently recovered.
`hardware_execution_verified` remains false.

Next is step 7 of `SATURN_MANAGER_HANDOFF.md`: prepare a Linux workload with a
self-checking vector load/arithmetic/store test, verify RVV and VLEN 256, and
collect console output, target cycle counters and shutdown on the exact AGFI.
Verify current worker ownership, running processes, SDK and slot state first.
The earlier scalar adapter hard-codes scalar target guards; do not bypass those
guards or relabel its scalar image as Saturn. No SPEC timing or role-3 search
should begin until the hardware gate passes.
