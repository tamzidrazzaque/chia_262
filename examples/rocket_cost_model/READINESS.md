# Rocket application prerequisites

Status: implementation checks pass; application execution is not ready.

## Completed

- Confirmed public single-core Rocket F2 image and AWS build metadata; see
  `IMAGE_DISCOVERY.md` and `image-discovery.json`.
- Created an isolated source checkout outside the research repository:
  `../rocket-build-source`. Chipyard is pinned to
  `19a07f6b8d4d1db81f5561d9aeceb2cdc43407fe`, with initialized FireSim
  `b7927ea504c501194eaec3e993c415f2270170f8` and Rocket Chip
  `55bcad0f59436de98ea510334121de8546b9e9d7`. Existing shared source trees
  were not modified. Other source dependencies and build environment still
  need initialization; exact pins alone do not verify the image interfaces.
- Installed this branch and its declared test dependencies into the isolated
  `../.venv` using Chipyard's Python 3.10 interpreter. No shared conda packages
  were changed. Worker images still require a separately verified matching
  Python/Ray environment.
- Added `chia/chipyard/rocket_target.py`: exact image, shell, source revision,
  driver hash and build-evidence gates, plus fresh AWS metadata validation.
- Added `RocketExperiment` application stages in `experiment.py`, using the
  inherited SPEC/QEMU/native-comparison/FPGA measurement stages and explicit
  Rocket tuning with loop and SLP vectorization disabled. The inherited
  Speckle build fixes the scalar ISA/ABI. Final linked instruction audit remains
  required before accepting an application image.
- Extracted hardware-validation and workload-flag hooks from the inherited
  `Experiment`; the default behavior still enforces the original MegaBOOM
  target. Existing MegaBOOM campaign regression checks pass.

## Checks run

```bash
../.venv/bin/python -m pytest -q \
  chia/chipyard/test/test_rocket_target.py \
  chia/chipyard/test/test_cost_model_loop.py \
  chia/chipyard/test/test_boom_model.py \
  chia/chipyard/test/test_boom_move_profile.py \
  chia/chipyard/test/test_next_iteration.py \
  chia/chipyard/test/test_spec2017_preparation.py \
  examples/boom_cost_model/tests
```

Run from this repository root. Result: **125 passed**. These are software
checks, not synthetic performance experiments, hardware runs or SPEC validation.

## Outstanding prerequisites

1. **Matching driver:** a dry-run invocation of the pinned FireSim makefile
   stopped because its generated `env.sh`/sourced build environment is absent.
   Docker is not installed on this host. The matching source workspace needs
   the pinned dependency/environment setup before driver elaboration/build.
   The make target also needs the Chipyard FireSim makefrag and correct platform
   target (`f2`); do not assume a generic `driver` invocation is sufficient.
   No matching driver bundle has been built or accepted. Preserve generated
   bridge/MMIO evidence and package shared-library dependencies after building.
2. **Licensed workload:** no usable SPEC CPU2017 installation or mounted worker
   was found in the inspected project and standard local locations. The owner
   must supply its path/host. Public source code cannot supply this asset.
3. **F2 worker:** the configured account/region has four stopped f2.6xlarge
   instances without Name tags and no running F2. No instance was started,
   reflashed or changed. Identify the project's worker or provision a dedicated
   worker before testing; ambiguous stopped instances are not assumed available.
4. **Cluster:** the new local Python environment is not a running worker cluster.
   Compiler/FireMarshal/FireSim resources and their mounts, pinned images,
   authenticated transport and worker identity need verification on the selected
   hosts. Existing cluster example files are not usable site configurations.
5. **Application gates:** run original-compiler test inputs with native SPEC
   comparison, then collect training baselines only after the driver, licensed
   workload, cluster and worker are accepted. No hardware correctness or timing
   result exists yet. The full adaptive Rocket controller and compiler rebuild
   identity adaptation remain later implementation work.

The adapter supplies reusable application stages, not a launch command for a
completed tuning campaign. A driver/build-evidence manifest with unverified or
missing artifacts is deliberately rejected. Repeating mocked software checks
cannot satisfy these missing application prerequisites.
