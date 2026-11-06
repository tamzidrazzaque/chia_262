# Manager takeover status

Outcome: **hardware execution gate passed**, 2026-11-05.
The driver remains accepted; the exact Saturn pair booted Linux and passed the
self-checking RVV test with VLEN 256. See `SATURN_RVV_GATE.md` and
`saturn-hardware-gate.json`.

The corrected handoff at `9c4a1a0` was pulled. Fresh AWS metadata verified the
available/public AGFI `agfi-012e92467d7d2149a`, AFI `afi-0d72fa6baed12e032`,
shell `0x10212415`, exact Saturn deploy quintuplet and FireSim `b7927ea...`.
The earlier source mismatch is resolved by the catalog/build-parent distinction.

A separate Chipyard checkout was prepared at:
`/home/ubuntu/cs262_compiler/chipyard-saturn-19a07f6`.
Its Chipyard, FireSim, Saturn, Rocket Chip and F2 SDK revisions match the handoff,
and all five source trees were clean at acceptance. Existing scalar/other
checkouts were not reset. No bitstream was rebuilt. The subsequent hardware gate reused one existing,
owner-authorized idle F2 worker and programmed the accepted Saturn image.

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

## Hardware gate completed; resume with SPEC preparation

The exact AGFI and deployed driver hash were verified on the worker before boot.
Linux exposed one Rocket processor and RVV. The test read `vlenb=32`, checked
full-vector and partial-vector load/add/store results, read increasing `cycle`
counters, exited 0 and powered down. FireSim reported `*** PASSED ***` after
3,770,962,967 simulation cycles. Collection and the manager completed successfully.
No driver process or simulation screen remained after collection.

`matching_source_verified` remains true for the accepted driver reconstruction.
`hardware_execution_verified` is now true, backed by `saturn-hardware-gate.json`.
The immutable driver-only acceptance receipt retains its original hardware-false
field; the later hardware receipt establishes the completed execution gate.

The existing F2 worker is running and idle with Saturn loaded, ready for the next
workload. Its private identity and live checks are recorded outside Git. Avoid
creating additional F2 workers unnecessarily.

Next: prepare unchanged SPEC roles 1 and 2 for this VLEN-256 target, validate
licensed inputs/expected outputs, then collect original-compiler baselines before
role-3 timing. Preserve the exact platform, compiler/ISA controls, input identities
and independent correctness gates. No SPEC performance run or adaptive search
was performed by this hardware smoke. The scalar execution adapter's guards
must remain intact; it is not the Saturn adapter.

## SPEC lane prepared; waiting for the producer bundle

See [SATURN_SPEC_LANE.md](SATURN_SPEC_LANE.md) for the exact private intake path,
bundle contract and commands. The lane verifies immutable GCC-15 role bundles,
stages overlays/configuration without constructing guests, reuses the accepted
native adapter/driver/base/probe, rejects stale or conflicting worker state and
collects hash-bound exact outputs. There is no GCC/SPEC rebuild path.

Only read-only worker preflight has been performed during this preparation.
No new final guest, SPEC execution or hardware run was launched. Resume at
bundle delivery plus its external manifest SHA-256, not at hardware dispatch.
The completed RVV gate's install descriptors were archived under the private
`rvv-gate-001/installed-workload` directory; its accepted images, binaries and
collected evidence remain unchanged.
