# Rocket resume runbook

## Workspace and private artifacts

These are checkpoint locations, not a promise that a new machine has the files.
Recheck paths, live instance state, IP and active processes before acting.

- Checkout: `/home/ubuntu/cs262_compiler/chia_262-rocket`.
- Local Python: `/home/ubuntu/cs262_compiler/.venv/bin/python`.
- Local backups: sibling `driver-bundle-001`, `zstd-pilot-001`, and
  `rocket-build-source`. The old pilot `-001` binary is not the canonical baseline.
- Selected worker: existing F2 instance `i-06397d31ea48ce801`, `us-east-1`.
  Last observed public IP: `100.53.77.240`; it can change after a restart.
  SSH user: `ubuntu`. Use the existing private SSH configuration/key; never copy
  credentials into this repository.
- Worker SDK: `/home/ubuntu/aws-fpga`, pinned as in ROCKET_HANDOFF.md.
- Worker Docker containers: `rocket-driver-build` and `rocket-guest-build`.
- Pinned intermediate Docker snapshot: `rocket-pinned-build:source-19a07f6`,
  image ID `sha256:7c9f5959306c1ef061adfe6a1938904e76775aa222164c699fa64d539ae65a92`.
  It predates the successful guest composition; copy guest artifacts separately.
- Worker host backups: `/home/ubuntu/rocket-artifacts/driver-bundle-001`,
  `compiler-snapshots`, `unchanged-rebuild.json`, `gcc-source.json`, and
  `gcc-configure-command.json` (verify actual contents).

Within `rocket-guest-build`:

| Location | Meaning |
| --- | --- |
| `/home/ray/rocket-artifacts/zstd-image-001` | Canonical workload archive, descriptor and identity |
| `/home/ray/rocket-artifacts/zstd-qemu-guest-001` | Successful full Linux QEMU evidence |
| `/home/ray/rocket-images/rocket-zstd-base-bash-coreutils-v1` | Built Linux base |
| `/home/ray/zstd-original-002`, `/home/ray/zstd-rebuilt-002` | Canonical equal application builds |
| `/home/ray/rocket-gcc` | Immutable unchanged compiler snapshot and build tree |
| `/home/ray/rocket-research` | Staged code; may be stale relative to this branch |
| `/home/ray/chipyard` | Pinned hardware source and toolchain |

Canonical zstd executable SHA-256:
`7f52374b3d691b32aea689d726b0d048c4bd1b0b648e7efe9774b909cb549084`.
Training input SHA-256:
`650c9a7263d5394f75a3923916ea9880f39bb916a07115096fce9da78304adc6`.
Unchanged compiler snapshot ID:
`1ade3ffa4b7a64471e8e1329254c2faefdb1302e85774d4bb8ce8a7c36d56998`.

## First actions

1. Inspect branch status and AWS instance state. Check Docker containers and
   `pgrep -x FireSim-f2` on the host. Do not start duplicate builds or drivers.
2. Copy guest image, QEMU evidence and Linux base from the guest container to
   persistent host storage, then back up locally. Hash the copies. Do not delete
   containers until their unique artifacts are safe.
3. Finish the private hardware manifest review. A locally prepared
   `../driver-bundle-001/hardware.reviewed.json` may exist; its referenced paths
   target worker host storage. Verify its evidence and fresh AWS image metadata,
   not just its boolean. Original `hardware.unverified.json` must remain intact.
4. Stage current code on the worker, e.g. `/home/ubuntu/rocket-code`.
   Do not run a stale container copy of the adapter or status fixes.
5. Create a dedicated runtime container from the pinned snapshot only if an
   equivalent one does not already exist. The CHIA host adapter requires
   privileged access, host PID/network namespaces and the owned host bind mount.
   This is separate from the guest build container. No Ray cluster is needed.

Example runtime layout, after inspecting existing containers:

```bash
sudo docker create --name rocket-runtime \
  --privileged --pid=host --network=host --cpus=4 --memory=16g \
  -v /home/ubuntu:/home/ubuntu:rslave \
  -e PYTHONPATH=/home/ubuntu/rocket-code \
  --entrypoint /bin/bash rocket-pinned-build:source-19a07f6 \
  -lc 'sleep infinity'
sudo docker start rocket-runtime
```

Inside that container, verify `/home/ray/firesim` resolves to the pinned
`/home/ray/chipyard/sims/firesim` (create the symlink if absent). Inspect deploy
configuration files and restore pinned sample build/hwdb/runtime configs where
needed; do not inherit unrelated campaign configuration. Prepare deploy log and
result directories. Check config paths against the pinned FireSim version.

Use `/home/ray/anaconda3/bin/python` for CHIA (Ray 2.54/Pydantic 2). Sourcing
Chipyard changes `python` to its separate environment, which is not the CHIA
controller interpreter. `PYTHONPATH` must point at the freshly staged code.
Before running, validate the reviewed manifest using `rocket_target`, verify the
IMDS instance ID, SDK revision and exact loaded slot image/shell. Do not weaken a
failed identity guard to proceed.

## First hardware pilot

After staging the private reviewed manifest and guest image on host storage:

```bash
sudo docker exec rocket-runtime /home/ray/anaconda3/bin/python \
  -m examples.rocket_cost_model.run_zstd_local_fpga \
  --hardware /home/ubuntu/rocket-artifacts/driver-bundle-001/hardware.reviewed.json \
  --image /home/ubuntu/rocket-artifacts/zstd-image-001 \
  --runtime /home/ubuntu/rocket-code/examples/firesim_spec/config_runtime.yaml \
  --instance-id i-06397d31ea48ce801 \
  --output /home/ubuntu/rocket-artifacts/zstd-fpga-pilot-001 \
  --phase pilot --sample 0 --timeout 1800
```

Run long jobs in the experiment owner's tmux/session, retain outer logs and use a
new output directory per attempt. The adapter takes a shared host lock, checks
idle hardware and provenance, records full measurement identities and rejects
incomplete/corrupt/non-scalar results. This command has not yet succeeded on
hardware; resolve integration failures before starting repeats or candidates.

On failure, inspect manager/UART/completion evidence and host processes first.
A manager timeout does not prove a detached driver exited. Do not relaunch or
reload the slot while any workload remains active. Preserve failed attempts.
Do not change SG/SSH policy or use the incompatible BOOM SDK workaround.

Accept the pilot only with successful completion/collection, exact decoded bytes,
matching input/binary identities and single-core scalar RV64 guest evidence.
Record compression and decompression separately, plus host wall time. One pilot
is not a speedup result or a variability estimate.

## Regression checks

From the checkout:

```bash
../.venv/bin/python -m pytest -q \
  examples/rocket_cost_model/tests \
  chia/chipyard/test/test_rocket_target.py \
  chia/chipyard/test/test_cost_model_loop.py \
  chia/chipyard/test/test_boom_model.py \
  chia/chipyard/test/test_boom_move_profile.py \
  chia/chipyard/test/test_next_iteration.py \
  chia/chipyard/test/test_spec2017_preparation.py \
  chia/trace/test/test_status_no_auto_init.py \
  chia/trace/test/test_profiler_no_auto_init.py \
  chia/firesim/test/test_native_manager_status.py \
  examples/boom_cost_model/tests
git diff --check
```

Checkpoint result: 164 passed. This selection is not the entire repository suite
or a substitute for hardware integration.

## Cost and session cleanup

The selected worker was originally stopped and was started for this setup.
It was last observed running and may still incur F2 charges. Inspect current
state rather than assuming it is stopped. After backing up artifacts and ensuring
no build, manager or driver is active, stop the dedicated instance when work is
finished; preserve its EBS volumes. Do not terminate it or touch the other F2s.
Record updated artifact locations, test outcomes and the exact next step in the
handoff after each milestone, then commit and push this research branch.
