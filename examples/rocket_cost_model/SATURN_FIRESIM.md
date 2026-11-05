# Official Saturn FireSim target

Lookup date: 2026-11-04 UTC. No FPGA was programmed and no hardware run was
performed during this lookup.

## What upstream provides

Chipyard publishes the exact target we need in its official FireSim catalog:

- catalog name:
  `firesim_saturn_REFV256D128_rocket_singlecore_no_nic_l2_llc4mb_ddr3`
- AGFI: `agfi-012e92467d7d2149a`
- target: `FireSimREFV256D128RocketConfig`
- platform: `WithAutoILA_FRFCFS16GBQuadRankLLC4MB_BaseF2Config`
- target frequency: 60 MHz
- expected deploy quintuplet:
  `f2-firesim-FireSim-FireSimREFV256D128RocketConfig-WithAutoILA_FRFCFS16GBQuadRankLLC4MB_BaseF2Config`

This is the released F2 image for the upstream single-core Rocket plus Saturn
REF configuration. It is not the scalar Rocket image and it is not the earlier
local `MINV128D64RocketConfig` probe.

The catalog entry first appears in Chipyard commit
`f503763b0c702ac3c423e58d8cc9d0975796a8c2`. AWS metadata shows that the image
was built from its immediate parent, Chipyard
`19a07f6b8d4d1db81f5561d9aeceb2cdc43407fe`, which pins:

- FireSim `b7927ea504c501194eaec3e993c415f2270170f8`
- Saturn `dfe75de2a8868d51d42c20612821431a9fcf645e`
- Rocket Chip `55bcad0f59436de98ea510334121de8546b9e9d7`

The publication commit added the finished AGFI/recipe and advanced FireSim to
`b2211da3...` in the same change. That newer submodule pin is not the image's
driver provenance. The target wrapper, Saturn and Rocket revisions, target
configuration hash and F2 SDK are unchanged across the two commits.

The machine-readable evidence is in `saturn-firesim-discovery.json`.

## What upstream does not provide

The F2 catalog entry has an `agfi` but no `driver_tar`. Therefore there is no
official standalone driver archive to download from that entry. This is normal
FireSim behavior: when `driver_tar` is absent, the manager builds the host
driver from the matching source tree. `firesim builddriver` performs this build
without launching an F2 run host.

So switching configs gives us the released hardware image and the source recipe
for its driver, but not an already-built driver binary. The driver is not
interchangeable across targets because it contains generated bridge and MMIO
interfaces for this exact quintuplet.

## Acceptance procedure

Use a clean checkout at the pinned Chipyard commit and initialize its
submodules. Do not use a newer FireSim checkout or the older local Chipyard
container merely because either can compile a driver.

1. In an AWS-authenticated manager environment, query
   `agfi-012e92467d7d2149a`. Record its AFI, shell, state, description, deploy
   quintuplet and `firesim-commit` tag.
2. Reject the image if the description does not name the expected quintuplet
   or the pinned FireSim revision above.
3. Point the FireSim runtime configuration at the official Saturn catalog
   name (as its default hardware configuration), then build only the driver:

   ```bash
   firesim builddriver \
     --runtimeconfigfile config_runtime.yaml \
     --buildrecipesconfigfile config_build_recipes.yaml \
     --hwdbconfigfile config_hwdb.yaml
   ```

   Run this from `sims/firesim/deploy` after adding the official AGFI entry to
   the manager-generated `config_hwdb.yaml`, as specified in the manager handoff.
4. Record the resulting `FireSim` SHA-256, generated-header hashes, dynamic
   library dependencies, source status and exact revisions. Package it as a
   `driver_tar` only after those checks pass.
5. On an F2 worker, run a minimal boot and RVV correctness test before SPEC.
   Only then freeze roles 1 and 2 and start the role-3 cost-model loop.

The current host has no usable AWS credentials, so step 1 and the actual driver
build have not been claimed as complete. The official image discovery is
complete; the matching-driver acceptance gate is still open.

The complete manager-side command sequence and reporting contract are in
`SATURN_MANAGER_HANDOFF.md`.
