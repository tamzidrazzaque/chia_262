# Saturn MCF/NAB reproduction handoff

This handoff records the source, accepted hardware pins, private artifacts, and
restart sequence needed to reproduce the current MCF/NAB experiment after the
F2 worker is returned. It describes reproduction of the accepted platform and
measurement method; it does not claim that an unmeasured candidate passed.

## Source snapshot

- Repository: `tamzidrazzaque/chia_262`
- Branch: `research/rocket-vector-cost-model`
- Experiment/recovery code: commit `d193f96`
- Sanitized paired results: commit `630b864`
- Current results and failures: [`ADAPTIVE_RUN_RESULTS_2026-11-24.md`](ADAPTIVE_RUN_RESULTS_2026-11-24.md)
- Platform acceptance and setup references: [`SATURN_RVV_GATE.md`](SATURN_RVV_GATE.md), [`SATURN_MANAGER_HANDOFF.md`](SATURN_MANAGER_HANDOFF.md), and [`SATURN_MANAGER_STATUS.md`](SATURN_MANAGER_STATUS.md)

The following files implement or test the experiment lane: `saturn_adaptive_loop.py`,
`saturn_adaptive_measure.py`, `saturn_chia_tasks.py`, `saturn_measure_hook.py`,
`saturn_paired_run.py`, `saturn_run_watchdog.py`, `saturn_spec/`, and the matching
`tests/` files. The active manager checkout had local changes during the runs;
the exact checkout state and its patch are retained in the private recovery
bundle. Do not replace code in a live manager while a measurement is dispatched.

## Accepted hardware and software identity

The already-qualified target is the public Saturn F2 AGFI
`agfi-012e92467d7d2149a`, shell `0x10212415`, VLEN 256. The accepted deployed
driver SHA-256 is
`5d3353ea8e6bf2891555da3d7d29122b1143a2e3d8c61a2a55741f1fd0bc94bd`; its
bundle SHA-256 is
`1b4784a9158ec170993e0bc9b59a2df2f730923664aa1bd563aebe9430634534`. The
accepted Linux boot binary SHA-256 is
`dbdf30cae7e8c88d3242c24a97591582686a0dbcc985b8b9cf34a72739673eb8`.

Use the pinned source revisions recorded in `saturn_spec/platform.py` and the
acceptance receipts: Chipyard `19a07f6b8d4d1db81f5561d9aeceb2cdc43407fe`,
FireSim `b7927ea504c501194eaec3e993c415f2270170f8`, Saturn
`dfe75de2a8868d51d42c20612821431a9fcf645e`, Rocket Chip
`55bcad0f59436de98ea510334121de8546b9e9d7`, and the F2 SDK
`80b34d3c25aff03353c0b4f2d304bb6067a5011d`. The FPGA image has passed its
hardware gate. Do not substitute an AGFI, driver, boot binary, or source
revision without repeating the corresponding acceptance checks.

## Private materials that must be restored securely

The following are intentionally outside Git because they include licensed or
machine-specific material:

- SPEC CPU2017 installation, license ISO, test inputs, and reference outputs.
- Frozen scalar, generic-vector, and candidate bundles plus their manifests and
  validation receipts.
- Manager runtime configuration, FireMarshal/FireSim work directories,
  `platform-lock.json`, trusted SSH known-hosts data, and the accepted driver
  output/package.
- Local compiler/CHIA environment and the private MCF/NAB runner configs,
  output directories, paired receipts, and raw manager evidence.

A permission-restricted recovery bundle and JSON checkpoint snapshots were
saved outside the repository. The bundle includes the current platform lock,
runner configurations and states, the local source patch, the manager checkout
patch, and exact manager-only file copies. Its SHA-256 manifest is checked
before use. The private archive is the source for machine-specific settings;
do not copy its worker address or host-key entry blindly to a replacement
instance.

## Restore and restart sequence

1. Clone the repository and check out `research/rocket-vector-cost-model` at
   `d193f96` or a later reviewed commit. Preserve the private recovery bundle
   separately; never add its contents to Git.
2. Restore the manager environment and the pinned Chipyard/FireSim checkouts
   using `SATURN_MANAGER_HANDOFF.md`. The existing AGFI avoids rebuilding the
   FPGA image. Restore the exact accepted driver bundle and verify its SHA-256
   before loading it on a worker.
3. Acquire an authorized F2 worker, load the accepted AGFI, and refresh the
   private platform lock for that instance. Confirm the instance ID, loaded
   image/shell, driver digest, SDK revision, disk capacity, and idle state with
   `saturn_spec preflight`. Use strict host-key verification; add a changed
   endpoint only after its key is independently verified against the trusted
   record. A returned/reassigned worker may have a different instance ID and
   network address.
4. Restore the private SPEC bundles and runner configurations. Keep MCF and NAB
   isolated on their assigned worker lanes. The current MCF bound is 2,952 guest
   seconds with a 7,200-second task alert; NAB uses its own saved bound. Both
   use `gpt-6-sol`. Do not reuse an output directory that already contains a
   `state.json`; create a fresh run directory and carry forward only validated
   paired feedback.
5. Run the read-only status monitor before dispatch:

   ```bash
   python3 examples/rocket_cost_model/saturn_status.py --config /private/path/status.json
   ```

   Confirm the manager and worker are idle and the platform preflight is fresh.
   Start a lane only from its private, restored configuration using the
   existing `saturn_adaptive_loop.py` entry point. Do not use QEMU timings as
   performance data.
6. Preserve each fresh role-2 control / role-3 candidate pair, exact output
   validation, target cycles, guest timing, worker/platform identity, and clean
   shutdown receipt. Update the sanitized results report after a pair completes;
   raw licensed outputs and manager logs stay private.

At the latest checkpoint, both controllers were blocked and both workers were
idle by read-only preflight. MCF stopped when its role-2 early-boot panic
receipt carried a refreshed platform hash that differed from the stale hash in
the controller policy; no candidate result was produced. NAB exhausted three
fresh role-2 boot attempts before dispatching its candidate. See the sanitized
results report and the permission-restricted private checkpoint for the exact
state. Do not infer a candidate result from either failure.
