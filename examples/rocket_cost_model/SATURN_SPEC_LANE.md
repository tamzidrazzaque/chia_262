# Saturn SPEC bundle intake and execution-lane preparation

The accepted platform remains the one at `f8a923f`: Saturn AGFI
`agfi-012e92467d7d2149a`, driver `FireSim-f2` SHA-256
`5d3353ea8e6bf2891555da3d7b29122b1143a2e3d8c61a2a55741f1fd0bc94bd`,
VLEN 256/DLEN 128, the hardware-tested native manager adapter, vector Linux base,
and the existing authorized worker. No GCC/SPEC rebuild is part of this lane.

**Current stop:** awaiting the incoming immutable bundle. No SPEC bundle has been
admitted, no final SPEC guest has been constructed and no new F2 workload has
been launched. Preparation has performed read-only platform/worker preflight.
Unit fixtures test validation only; they are not synthetic performance workloads.

## Private delivery path

Deliver a directory, not an archive, at:

```text
/home/ubuntu/cs262_compiler/saturn-spec-lane/incoming/<manifest-sha256>/
```

Send the complete lowercase SHA-256 of its `manifest.json` separately. Upload to
a temporary sibling directory and atomically rename only when transfer completes.
Do not include links, special files, absolute paths, dot/dot-dot path components,
unlisted payloads or duplicate JSON keys. Every regular file except
`manifest.json` must appear in `files_sha256`. Hash manifest bytes last; it does
not hash itself. SHA-256 checks establish integrity and identity, not independent
proof of the producer's compiler build or licensing provenance.

Other private locations:

- `.../saturn-spec-lane/platform-lock.json`: frozen paths/hashes for the accepted
  driver/bundle, native adapter, Linux base/config, BusyBox config, accepted RVV
  probe, runtime template and existing ELF audit tools.
- `.../saturn-spec-lane/verified/<manifest-sha256>/bundle/`: verified copies.
- `.../saturn-spec-lane/staging/<new-run>/`: future per-sample overlay/plan/configs.
- `.../saturn-spec-lane/preflight/`: private read-only worker observations.
- `.../saturn-spec-lane/results/`: future raw/validated run artifacts.

All licensed binaries, inputs, goldens, SPEC logs, raw timing data, site
configuration and host identities stay outside Git. Only sanitized code,
schemas, unit tests and documentation are published.

## Exact incoming contract

The machine-readable contract is
[`saturn_spec/bundle.schema.json`](saturn_spec/bundle.schema.json). Python
verification additionally enforces cross-file identities, actual ELF auditing,
role/flag consistency, full file hashes and SPEC validation evidence. Schema
validation alone is insufficient.

`manifest.json` contains exactly these fields (replace placeholders):

```json
{
  "schema_version": 1,
  "role": "2-generic-vector",
  "candidate_id": null,
  "benchmark": "648.exchange2_s",
  "input_id": "exchange2-test-1",
  "size": "test",
  "source_variant": "unchanged SPEC CPU2017 source",
  "target": {
    "agfi": "agfi-012e92467d7d2149a",
    "driver_sha256": "5d3353ea8e6bf2891555da3d7b29122b1143a2e3d8c61a2a55741f1fd0bc94bd",
    "quintuplet": "f2-firesim-FireSim-FireSimREFV256D128RocketConfig-WithAutoILA_FRFCFS16GBQuadRankLLC4MB_BaseF2Config",
    "vlen_bits": 256,
    "dlen_bits": 128
  },
  "compiler_manifest": "metadata/compiler.json",
  "isa_metadata": "metadata/isa.json",
  "validation_manifest": "metadata/validation.json",
  "executable": "payload/program",
  "inputs": {"input.dat": "payload/input.dat"},
  "expected_outputs": {"stdout.txt": "reference/stdout.txt"},
  "argv": ["./program", "input.dat"],
  "stdin": null,
  "stdout": "stdout.txt",
  "stderr": "stderr.txt",
  "files_sha256": {
    "payload/program": "<64 hex digits>",
    "payload/input.dat": "<64 hex digits>",
    "reference/stdout.txt": "<64 hex digits>",
    "metadata/compiler.json": "<64 hex digits>",
    "metadata/isa.json": "<64 hex digits>",
    "metadata/validation.json": "<64 hex digits>",
    "metadata/validation.log": "<64 hex digits>"
  }
}
```

The example filenames and argv are illustrative; the producer must supply the
real unchanged SPEC invocation and files. `inputs` maps work-directory filenames
to bundled payload files (an empty mapping is allowed for genuinely argv-only inputs). `stdin` is null or an input destination. `argv` is a
bounded argument array beginning `./program`, quoted as arguments rather than
interpreted as shell source. Work filenames use letters/digits/underscore/dot/
plus/hyphen/slash, canonical relative paths, and cannot collide with `program`,
input files, or file/directory prefixes. stdout/stderr must differ.

`expected_outputs` maps generated work filenames to **producer-validated exact
golden output files**. This version supports exact bytes only. It does not
implement SPEC numeric-tolerance/specdiff comparators on the manager. The
producer must bind these particular golden bytes to a successful SPEC validation;
do not substitute official reference hashes that permit tolerance differences.
Unsupported comparator needs should block intake, not silently weaken checks.

Allowed roles are `1-scalar`, `2-generic-vector`, `3-saturn-aware`. Role 1 is a
valid scalar reference **on Saturn**; scalar Rocket execution adapters/images
are rejected. Roles 1/2 require null candidate IDs. Role 3 requires a 12–32 hex
prefix matching its compiler manifest's full 64-digit candidate ID.

### Referenced compiler manifest

Required fields:

```json
{
  "gcc_version": "15.1.0",
  "gcc_revision": "1b306039ac49f8ad91ca71d3de3150a3c9fa792a",
  "role": "2-generic-vector",
  "target_flags": "-march=rv64gcv_zvbb -mabi=lp64d -mtune=rocket -mrvv-vector-bits=zvl -fvect-cost-model=dynamic -fopt-info-vec-all",
  "compiler_sha256": "<64 hex digits>",
  "snapshot_id": "<64 hex digits>",
  "candidate_id": null
}
```

Flags must exactly match `role_settings` in `spec_vector_baseline.py`. Scalar
role flags are `-march=rv64gc -mabi=lp64d -mtune=rocket
-fno-tree-loop-vectorize -fno-tree-slp-vectorize`. No GCC 13 role/compiler rebuild
is admitted. The independent ELF audit requires GCC 15.1 provenance; GCC 13
comments contributed by linked runtime objects do not invalidate an otherwise
GCC-15-built executable. The existing GCC-13-built RVV platform probe is reused
byte-for-byte as a platform helper, never substituted for the SPEC executable.

### Referenced ISA metadata

Required fields: `elf_sha256`, `riscv_arch` (exact readelf attribute string),
`abi: "lp64d"`, `linkage: "static"`, `vlen_bits: 256`, `dlen_bits: 128`, and
integer `static_rvv_instruction_count`. The manager independently runs the
existing readelf/objdump tools, requires ELF64 little-endian RISC-V double-float
ABI/static linking, matches the architecture and instruction count, and rejects
unsupported extensions or minimum VLEN above 256. Role 1 must contain no RVV;
roles 2/3 must contain RVV. Incompatible disassembly is a rejection, not permission
to skip auditing. Tools are hash-locked; no compiler or toolchain is rebuilt.

### Referenced producer validation manifest

Required fields:

- `status: "passed"`, `spec_validation: "passed"`, `backend: "qemu"`.
- Exact `role`, `benchmark`, `size` (`test`, `train`, or `ref`), `input_id`,
  `source_variant`, `target_vlen: 256`, `target_dlen: 128`.
- `elf_sha256`, `compiler_manifest_sha256`, `isa_metadata_sha256`.
- `invocation_sha256`: SHA-256 of UTF-8 JSON for `{argv, stdin, stdout, stderr}`,
  with keys sorted and separators `(",", ":")`, using Python `json.dumps` defaults.
  This binds validation to the exact invocation, not just the ELF and files.
- `inputs_sha256`: work destination -> input file SHA-256.
- `expected_outputs_sha256`: work output destination -> validated golden SHA-256.
- `validation_log`: bundled, hashed SPEC validation log with the explicit
  ` Success <benchmark> base <size>` line accepted by `validated()`.

The producer's QEMU validation is a functional prerequisite only. It is never
used as a Saturn performance label. The manager cannot independently re-run SPEC's
licensed validator before receipt of the bundle and does not claim to do so.

## Prepared commands and enforced stops

From this repository root, the preparation entry point is:

```bash
../.venv/bin/python -m examples.rocket_cost_model.saturn_spec --help
```

It has only `intake`, `stage`, `preflight`, `verify-image`, and `collect` commands.
There is no compiler build, SPEC build, guest construction or hardware dispatcher
command. **Do not run the following intake/staging steps until the real bundle
and its external manifest digest arrive.**

```bash
LANE=/home/ubuntu/cs262_compiler/saturn-spec-lane
../.venv/bin/python -m examples.rocket_cost_model.saturn_spec intake \
  --platform "$LANE/platform-lock.json" \
  --bundle "$LANE/incoming/<manifest-sha256>" \
  --manifest-sha256 '<manifest-sha256>' --verified-root "$LANE/verified"
../.venv/bin/python -m examples.rocket_cost_model.saturn_spec stage \
  --platform "$LANE/platform-lock.json" \
  --snapshot "$LANE/verified/<manifest-sha256>" \
  --out "$LANE/staging/<new-run>" --phase baseline --sample 0
```

Intake verifies before copying and re-verifies its content-addressed snapshot.
Failed intake remains explicitly rejected. Existing snapshots/stages/results
cannot be overwritten. Staging re-verifies all bundle hashes before emitting
an overlay, a FireMarshal workload descriptor, runtime/HWDB configuration,
adapted native manager script and hash-bound plan. **It does not build an image.**
Rootfs capacity accounts for the base, bundled bytes, runtime working copies,
expected output copies and `--scratch-mib` (default 1024), rounded up to whole
GiB with a 2-GiB minimum. Adjust scratch space from the producer’s measured disk
needs, and freeze one capacity across paired roles before construction.
The HWDB uses the accepted local `driver-bundle.tar.gz` as `driver_tar`, preventing
the native manager from rebuilding the driver. The adapted script reuses the
hardware-tested native adapter, changing config paths and adding execution guards;
it retains strict known-host checks and the prepared SDK policy.

Every stage has a fresh nonce and full role/input/platform/worker/phase/sample
identity. The future guest rechecks ELF/input hashes, runs the reused VLEN-256
probe, invokes the unchanged SPEC argv once, records POSIX BusyBox elapsed/user/
system times, and collects expected outputs and completion markers. Elapsed time
includes process startup and I/O; whole-simulation cycle counts include boot.
Neither is silently substituted for a narrower SPEC code-region cycle count.
The BusyBox timer has finite resolution; zero elapsed readings are rejected.
Characterize pilot durations before using short test inputs for timing comparisons.

## After bundle delivery, before any later execution

Final guest construction is deliberately not performed by this preparation task.
After reviewing the received bundle and stage, the next authorized step is to
construct/install that descriptor with the existing FireMarshal base. No GCC or
SPEC rebuild should be necessary. If FireMarshal requests a base/kernel/toolchain
rebuild, stop and investigate the frozen platform hashes rather than rebuilding.

Then use `verify-image` with the stage, rootfs, bootbinary and
`--out <stage>/image-receipt.json`. It reads required ext4 files with debugfs and
compares every overlay hash, rejects stale identity/runner/payload bytes, and
requires the accepted bootbinary. It performs no construction or hardware action.

A fresh read-only check is:

```bash
../.venv/bin/python -m examples.rocket_cost_model.saturn_spec preflight \
  --platform /home/ubuntu/cs262_compiler/saturn-spec-lane/platform-lock.json \
  --out /absolute/private/new-stage/preflight.json
```

It verifies source revisions and platform hashes, strict SSH host identity,
physical instance ID, SDK, loaded Saturn AGFI/shell, deployed driver and libraries,
absence of simulation processes/screens, and availability of the shared worker
lock. Its observation expires in 300 seconds; it releases the lock immediately
and does not reserve the worker. Refresh before each native task. Recognized
`deploy/workloads/saturn-spec-<24 hex>` install descriptors are runtime artifacts;
tracked source changes and other untracked hardware files still fail preflight.
Completed RVV gate install descriptors were archived privately to preserve the
clean hardware checkout; their accepted images and raw evidence are unchanged.

The staged native script refuses execution unless the stage, admitted image,
installed workload descriptor and fresh preflight agree. It holds the worker-side
lock for the complete native task, rejects repeated attempts of the same task in
a stage, records completion from the real process exit, repeats live target/idle checks under that
lock, and verifies staged worker image bytes before `runworkload`. An outer
controller must still impose finite timeouts, retain logs and inspect detached
processes after a timeout; no such controller is launched here.

## Result-collection contract

The guarded native adapter records `<task>-completion.json` from the actual
manager exit (including nonzero failures), rather than trusting incoming producer
metadata. Use `<stage>/runworkload-completion.json` for collection. Its fields are:
`backend: "fpga"`, `task: "runworkload"`, `returncode: 0`, `image_id`, `worker_id`,
`worker_lease_held: true`, `agfi`, `driver_sha256`, `vlen_bits: 256`, `phase`,
`sample`, numeric `started_at`/`finished_at` (Unix seconds), `plan_sha256`,
`image_receipt_sha256`, and `preflight_sha256`. These describe the actual native
run; they must not be synthesized from incoming producer/QEMU metadata.

`collect` requires `--stage`, `--image`, `--completion`, `--preflight`,
`--collected` (the single FireSim job directory), and a new private `--out`.
It rejects mismatched image/runtime/role/input/worker/phase/sample, expired
preflight at start, changed image bytes, failure/partial collection, missing
shutdown/simulation pass, wrong in-guest VLEN/probe/ELF, nonpositive elapsed time,
and any exact expected-output mismatch. No result is scored on infrastructure
failure. Keep raw results private and use fresh stages for independent repeats.

## Validation and current handoff

Tests exercise invalid/tampered bundles, copy-time changes, role/compiler/ISA
mismatches, source-status checks, stale overlays/images, failed/partial collection,
wrong VLEN/driver, expired preflight and unconstructed-guest refusal. Positive
unit fixtures mock ELF inspection and never execute a benchmark. Real incoming
ELFs will receive the independent audit during intake.

The read-only setup preflight passed on the existing idle authorized worker.
No actual incoming bundle, final SPEC guest or SPEC hardware run has been tested.
The next agent should obtain the directory and external manifest digest matching
the contract above, then resume at intake; preserve the explicit construction/
execution boundary until delivery.
