# Saturn F2 manager handoff

This handoff is for the agent running on the AWS FireSim manager instance. The
goal is to build and verify the host driver for the released Rocket plus Saturn
F2 image. Do not rebuild the FPGA image.

Manager checkpoint: the matching driver was accepted on 2026-11-05. Read
[SATURN_MANAGER_STATUS.md](SATURN_MANAGER_STATUS.md) and
[saturn-driver-acceptance.json](saturn-driver-acceptance.json) before rebuilding.
Step 7 also passed on 2026-11-05: see
[saturn-hardware-gate.json](saturn-hardware-gate.json) and
[SATURN_RVV_GATE.md](SATURN_RVV_GATE.md). Resume with SPEC workload preparation;
do not rebuild or rerun the completed platform gate without a reason.
The prepared SPEC intake/staging lane and sender contract are in
[SATURN_SPEC_LANE.md](SATURN_SPEC_LANE.md). Wait for the immutable bundle and
external manifest digest before final guest construction or execution.

## Current roles 1/2 workload handoff

The software-preparation host has produced a deterministic private archive for
the first paired baseline run. It contains unchanged-SPEC role 1 and role 2
executables, official test inputs, the official reference output, and a
manifest. It contains licensed SPEC material and therefore remains outside
Git. Accept only this identity:

```text
archive: saturn-spec-roles-1-2.tar
SHA-256: 9c6331dea7f03a6e9364df4305d8ce0dae696ab5f683feb0c37208ce9bdb10ca
role 1 ELF: 6500e7e82a183d11d5e83b0ff4b3ee79fc709127c849b8c2fca1675307d27e7d
role 2 ELF: 933c5062989468d8eba30c72a08dadb2e15bf39dfffff2532f5f2fed5cada541
expected s.txt: 93c5882eda07b05bf277b4636f8a92cd16bf347e8cf5513fc578b8f60c12506e
```

Before staging, hash the archive, inspect `manifest.json`, and verify every
member hash. Reject a different target, VLEN, compiler flag set, ELF, input, or
reference. Prepare the FireMarshal adapter and measurement protocol in
parallel, but do not substitute locally rebuilt binaries or start a hardware
run until this exact private archive has been transferred. Run roles in paired,
order-balanced fresh boots with identical inputs and platform settings. Require
the exact output hash and clean shutdown for every measured sample; retain raw
target-cycle observations and platform identities outside Git.

The producer is:

```bash
python3 -m examples.rocket_cost_model.bundle_spec_roles \
  --spec-dir /home/eecs/trazzaque/spec2017-research/install \
  --evidence /home/eecs/trazzaque/spec2017-research/results/saturn-vlen256-baselines \
  --output /home/eecs/trazzaque/spec2017-research/results/saturn-vlen256-baselines/saturn-spec-roles-1-2.tar
```

## Fixed target identity

Do not substitute a newer checkout, scalar Rocket image, BOOM image, or the
historical `MINV128D64RocketConfig` probe.

- Chia branch: `research/rocket-vector-cost-model`
- hardware catalog name:
  `firesim_saturn_REFV256D128_rocket_singlecore_no_nic_l2_llc4mb_ddr3`
- AGFI: `agfi-012e92467d7d2149a`
- expected deploy quintuplet:
  `f2-firesim-FireSim-FireSimREFV256D128RocketConfig-WithAutoILA_FRFCFS16GBQuadRankLLC4MB_BaseF2Config`
- Chipyard build source: `19a07f6b8d4d1db81f5561d9aeceb2cdc43407fe`
- FireSim build source: `b7927ea504c501194eaec3e993c415f2270170f8`
- Saturn: `dfe75de2a8868d51d42c20612821431a9fcf645e`
- Rocket Chip: `55bcad0f59436de98ea510334121de8546b9e9d7`
- F2 SDK: `80b34d3c25aff03353c0b4f2d304bb6067a5011d`
- catalog publication: `f503763b0c702ac3c423e58d8cc9d0975796a8c2`

The target is one Rocket core with Saturn `VectorParams.refParams`, VLEN 256,
DLEN 128, and a 128-bit system bus.

The catalog-publication commit is not the driver source revision. Its immediate
parent is the build-source revision above. The publication commit adds the
finished AGFI and F2 recipe while simultaneously advancing FireSim by one
follow-up commit. AWS embeds the parent's `b7927ea...` revision in the image,
so the parent is authoritative for the matching driver.

## 1. Inspect the manager before changing it

Record the existing manager checkout, configuration and AWS identity. Do not
modify a shared or dirty Chipyard checkout.

```bash
aws sts get-caller-identity
aws configure get region
git -C /explicit/path/to/existing/chipyard status --short
git -C /explicit/path/to/existing/chipyard rev-parse HEAD
```

If the existing path is unknown, locate it read-only first. Create a separate
checkout for this target rather than resetting an existing tree.

## 2. Verify the released AGFI

Use the manager's configured AWS region. This is a read-only query and does not
launch an instance or program an FPGA.

```bash
aws ec2 describe-fpga-images \
  --filters Name=fpga-image-global-id,Values=agfi-012e92467d7d2149a \
  --query 'FpgaImages[0].{AFI:FpgaImageId,AGFI:FpgaImageGlobalId,State:State.Code,Public:Public,Shell:ShellVersion,Description:Description}' \
  --output json
```

Stop if the image is absent or not `available`. The description must contain
both the expected deploy quintuplet and FireSim revision above. Save the query
result privately; commit only the sanitized AFI, state, shell, quintuplet and
revision. Do not copy AWS account information into Git.

## 3. Prepare the exact source checkout

Choose an explicit manager-local destination with sufficient storage. The path
below is an example; change it explicitly if the manager uses a different data
volume.

```bash
SATURN_MANAGER_ROOT=/scratch/trazzaque/chipyard-saturn-19a07f6
git clone https://github.com/ucb-bar/chipyard.git "$SATURN_MANAGER_ROOT"
git -C "$SATURN_MANAGER_ROOT" checkout --detach 19a07f6b8d4d1db81f5561d9aeceb2cdc43407fe
cd "$SATURN_MANAGER_ROOT"
./build-setup.sh
```

`build-setup.sh` is intentionally the pinned checkout's official setup path.
Do not point this source tree at an environment from a different Chipyard
release merely to make the build pass.

After setup, verify the important pins:

```bash
git rev-parse HEAD
git -C sims/firesim rev-parse HEAD
git -C generators/saturn rev-parse HEAD
git -C generators/rocket-chip rev-parse HEAD
git -C sims/firesim/platforms/f2/aws-fpga-firesim-f2 rev-parse HEAD
git status --short
```

The revisions must match the fixed identity above and the source tree must be
clean before the driver is accepted.

## 4. Initialize the manager configuration

```bash
cd "$SATURN_MANAGER_ROOT/sims/firesim"
source sourceme-manager.sh
cd deploy
firesim managerinit --platform f2
```

Run `managerinit` only in this new checkout. It replaces that checkout's
`config_runtime.yaml`, `config_build.yaml`, `config_build_recipes.yaml`, and
`config_hwdb.yaml`, retaining backups. Existing AWS credentials may be kept by
pressing Enter when prompted.

In the generated `config_runtime.yaml`, retain FPGA simulation mode and select
the official hardware catalog entry:

```yaml
metasimulation:
  metasimulation_enabled: false

target_config:
  topology: no_net_config
  no_net_num_nodes: 1
  default_hw_config: firesim_saturn_REFV256D128_rocket_singlecore_no_nic_l2_llc4mb_ddr3
```

Do not replace the rest of the manager-generated run-farm configuration with
this excerpt.

The matching source revision predates publication of the catalog entry. Add
the following official entry from the publication commit to the generated
`config_hwdb.yaml`:

```yaml
firesim_saturn_REFV256D128_rocket_singlecore_no_nic_l2_llc4mb_ddr3:
  agfi: agfi-012e92467d7d2149a
  deploy_quintuplet_override: null
  deploy_makefrag_override: ../../../generators/firechip/chip/src/main/makefrag/firesim
  custom_runtime_config: null
```

This is manager configuration, not a change to the pinned hardware source.
The three-parent relative path above is for `sims/firesim/deploy/config_hwdb.yaml`.
The publication catalog lives in a different directory, so copying its two-parent
path here fails resolution. An absolute path to the same pinned makefrag directory
also works; that was used in the verified manager build.

## 5. Build only the matching driver

From `sims/firesim/deploy`:

```bash
firesim builddriver \
  --runtimeconfigfile config_runtime.yaml \
  --buildrecipesconfigfile config_build_recipes.yaml \
  --hwdbconfigfile config_hwdb.yaml
```

This should build locally on the manager without launching an F2 worker. It
must not invoke `firesim buildbitstream`.

For the pinned FireSim revision, the expected output directory is:

```text
sims/firesim/sim/output/f2/f2-firesim-FireSim-FireSimREFV256D128RocketConfig-WithAutoILA_FRFCFS16GBQuadRankLLC4MB_BaseF2Config/
```

The verified F2 driver binary name in that directory is `FireSim-f2`. Locate it with:

```bash
rg --files ../sim/output/f2 | rg '/FireSim-f2$'
```

## 6. Capture driver acceptance evidence

Set `SATURN_DRIVER` to the explicit path printed above, then record:

```bash
sha256sum "$SATURN_DRIVER"
file "$SATURN_DRIVER"
ldd "$SATURN_DRIVER"
git -C "$SATURN_MANAGER_ROOT" status --short
git -C "$SATURN_MANAGER_ROOT/sims/firesim" status --short
```

Also hash the regular files under the matching
`sims/firesim/sim/generated-src/f2/<quintuplet>/` directory. Reject the driver
if `ldd` reports a missing library, the generated quintuplet differs, or the
source revisions differ. A successful compilation alone is not matching-image
proof.

Update `saturn-firesim-discovery.json` with sanitized facts only:

- AFI, state and shell from AWS
- verified FireSim revision and deploy quintuplet
- driver SHA-256 and generated-header hashes
- build host OS/tool versions
- `matching_source_verified: true` only after every identity check passes

Keep credentials, account IDs, private hostnames, binaries and raw manager logs
outside Git.

## 7. Hardware execution gate

After driver acceptance, configure the existing FireMarshal/Linux workload and
launch one F2 simulation node. The first run is a boot plus self-checking RVV
smoke, not SPEC performance. Verify:

1. Linux boots on the exact AGFI and driver.
2. The guest exposes RVV with VLEN 256.
3. A self-checking vector load, arithmetic operation and store pass.
4. Console output, target cycle counters and shutdown are collected normally.

Only after this gate passes should the agent regenerate unchanged-SPEC roles 1
and 2 for the VLEN-256 target and start paired role-2 versus role-3 timing.

## Report back

Commit and push sanitized documentation and manifests to
`research/rocket-vector-cost-model`. Report one of these outcomes explicitly:

- `driver accepted`: all image, source, quintuplet, dependency and hash checks
  passed;
- `driver built but unverified`: compilation passed but image metadata or an
  acceptance check is missing;
- `blocked`: include the exact failing command and first relevant error.

Never relabel a scalar Rocket, BOOM, Ara, MINV128D64, or differently pinned
driver as this target.
