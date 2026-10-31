# Rocket F2 image discovery

Lookup date: 2026-10-31 UTC. No instances were launched or FPGAs programmed.
AWS metadata was queried read-only using the configured local account.

## Primary candidate: single-core Rocket

- Public catalog entry: `firesim_rocket_singlecore_no_nic_l2_lbp`.
- AGFI: `agfi-033a86c6e5d006fc8`.
- Regional AFI: `afi-065352b4754b46048`, `us-east-1`.
- AWS reports `available`, public, shell `0x10212415`.
- Target: `WithDefaultFireSimBridges_WithFireSimHighPerfConfigTweaks_chipyard.RocketConfig`.
- Platform: `BaseF2Config`.
- FireSim revision in AWS image description:
  `b7927ea504c501194eaec3e993c415f2270170f8`.

The [upstream catalog](https://github.com/ucb-bar/chipyard/blob/157dd69e49b9866be2bf8db390ee78bc38cd4438/sims/firesim-staging/sample_config_hwdb.yaml)
contains this image and the MegaBOOM AGFI used in the handoff. Querying AWS
confirms this is an F2 image rather than an obsolete F1 tutorial image. The
single-core configuration is the primary candidate for our scalar application
campaign. Its `BaseF2Config` memory model is not the MegaBOOM FRFCFS/LLC model;
verify and report its runtime parameters explicitly.

## Alternative: closer memory configuration, four Rocket cores

`firesim_rocket_quadcore_no_nic_l2_llc4mb_ddr3`:
AGFI `agfi-0c5eedfce0e568971`, AFI `afi-08cbadc60414057da`.
AWS reports public, available, shell `0x10212415`, same FireSim revision.
Its target is `WithDefaultFireSimBridges_WithFireSimTestChipConfigTweaks_chipyard.QuadRocketConfig`
and platform is `WithAutoILA_FRFCFS16GBQuadRankLLC4MB_BaseF2Config`.
This is closer to the handoff memory configuration, but four cores are a target
difference. A one-thread workload would need verified affinity and idle-hart
behavior; it must not be described as the single-core image.

Saturn/vector, Gemmini and private custom JTAG/debug images are not selected.
The single-core and quad-core candidates above already exist; no Vivado image
build is justified merely to start this investigation.

## Following the MegaBOOM handoff

The handoff pins AGFI/AFI, exact quintuplet, shell, source revisions and a hash
of its matching driver bundle before accepting hardware observations. We have
verified image existence, metadata and public catalog identity for Rocket.
We have not yet reached the handoff's driver/source acceptance gate.

The handoff Chipyard revision `19a07f6b8d4d1db81f5561d9aeceb2cdc43407fe`
pins the same FireSim revision as both Rocket images and Rocket Chip revision
`55bcad0f59436de98ea510334121de8546b9e9d7`. Its source contains the matching
Rocket target mixins. This is a candidate driver source tree, not proof that
all build inputs/generated bridge interfaces match the image. Current upstream
main has newer submodules; building from latest main blindly is inappropriate.

`image-discovery.json` saves public image identities and hashes of the inspected
pinned source files. `matching_source_verified` remains false, and the driver
fields remain null, deliberately preventing this discovery record from being
mistaken for a ready-to-run hardware manifest.

Next steps:

1. Locate the official matching driver/build archive or reconstruct the exact
   driver from verified image build provenance and the pinned source tree.
   Build driver software only; do not rebuild the FPGA bitstream by default.
2. Verify generated bridge/MMIO metadata and target parameters, and package the
   driver plus required shared libraries using the handoff packaging approach
   in `chia/firesim/bitstream_build_node.py`. Record hashes and dependency versions.
3. Add a Rocket-specific manifest/preflight to the application controller.
   Preserve MegaBOOM's exact checks rather than relabeling its target.
4. On an available verified F2 worker, run licensed application test inputs
   with native output comparison, then establish training baselines. QEMU may
   validate functionality; it cannot supply Rocket performance labels.

Existing shared Chipyard trees differ from the candidate source revision and
contain custom work. They were inspected without modifying them. No trusted
matching driver bundle was found in the searched local project/build locations.

The [FireSim manager documentation](https://docs.fires.im/en/1.22.0/advanced-usage/manager/manager-configuration-files/)
explains `driver_tar`, which allows a prebuilt driver to be deployed separately
from a hardware image. The AGFI itself is not a downloadable driver bundle.
