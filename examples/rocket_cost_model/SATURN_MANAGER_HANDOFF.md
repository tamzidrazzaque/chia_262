# Saturn F2 manager handoff

This handoff is for the agent running on the AWS FireSim manager instance. The
goal is to build and verify the host driver for the released Rocket plus Saturn
F2 image. Do not rebuild the FPGA image.

## Fixed target identity

Do not substitute a newer checkout, scalar Rocket image, BOOM image, or the
historical `MINV128D64RocketConfig` probe.

- Chia branch: `research/rocket-vector-cost-model`
- hardware catalog name:
  `firesim_saturn_REFV256D128_rocket_singlecore_no_nic_l2_llc4mb_ddr3`
- AGFI: `agfi-012e92467d7d2149a`
- expected deploy quintuplet:
  `f2-firesim-FireSim-FireSimREFV256D128RocketConfig-WithAutoILA_FRFCFS16GBQuadRankLLC4MB_BaseF2Config`
- Chipyard: `f503763b0c702ac3c423e58d8cc9d0975796a8c2`
- FireSim: `b2211da3b1a57dbf6f601629fbe52490e22827a8`
- Saturn: `dfe75de2a8868d51d42c20612821431a9fcf645e`
- Rocket Chip: `55bcad0f59436de98ea510334121de8546b9e9d7`
- F2 SDK: `80b34d3c25aff03353c0b4f2d304bb6067a5011d`

The target is one Rocket core with Saturn `VectorParams.refParams`, VLEN 256,
DLEN 128, and a 128-bit system bus.

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
SATURN_MANAGER_ROOT=/scratch/trazzaque/chipyard-saturn-f503763b
git clone https://github.com/ucb-bar/chipyard.git "$SATURN_MANAGER_ROOT"
git -C "$SATURN_MANAGER_ROOT" checkout --detach f503763b0c702ac3c423e58d8cc9d0975796a8c2
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

## 5. Build only the matching driver

From `sims/firesim/deploy`:

```bash
firesim builddriver \
  --runtimeconfigfile config_runtime.yaml \
  --buildrecipesconfigfile ../../firesim-staging/sample_config_build_recipes.yaml \
  --hwdbconfigfile ../../firesim-staging/sample_config_hwdb.yaml
```

This should build locally on the manager without launching an F2 worker. It
must not invoke `firesim buildbitstream`.

For the pinned FireSim revision, the expected output directory is:

```text
sims/firesim/sim/output/f2/f2-firesim-FireSim-FireSimREFV256D128RocketConfig-WithAutoILA_FRFCFS16GBQuadRankLLC4MB_BaseF2Config/
```

The normal driver binary name in that directory is `FireSim`. Locate it with:

```bash
rg --files ../sim/output/f2 | rg '/FireSim$'
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
