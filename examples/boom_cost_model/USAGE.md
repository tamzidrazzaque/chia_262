# BOOM GCC cost-model experiment

For the separate experimental `-mtune=boom` compiler, batched kernel screening,
hardware-labeled surrogate and measurement queue, see [EXPERIMENT_PLAN.md](EXPERIMENT_PLAN.md).
The original SPEC loop below continues to use the historical Rocket-cost
experiment; the new fast-screen pipeline uses explicit compiler manifests.

This controller uses the user's authenticated Claude CLI on the controller host.
It uses Chia's existing compiler, FireMarshal and F2 workers. It never launches
instances, builds a new FPGA image, changes security groups, or enables SSH
GatewayPorts. Keep the site's authenticated Ray transport and listener guard.

The initial experiment is SPEC2017 intspeed **MCF and Exchange2 only** on the
verified public FRFCFS/LLC MegaBOOM image, AGFI `agfi-0f4582f3f39b9a8a4`. It is
not the separate intended FCFS16 configuration, a full-suite result, or a
reportable SPEC score. Supply a licensed, writable SPEC installation to the
compiler worker using `SPEC_DIR_2017` as in the existing SPEC build example.

## Compiler preparation

The installed baseline is GCC 13.2.0, source revision
`c891d8dc23e1a46ad9f3e757d09e57b500d40044`, from riscv-tools 1.0.6/feedstock
`56c29e0`, toolchain revision `9a28c809a5d355874def06a414aa5f272fae564d`.
`prepare_gcc.py` downloads its full pinned source archive and verifies its hash.
It uses installed host flex and the worker's existing GMP/MPFR/MPC. Run from
the repository root after activating the Chia Python environment:

```bash
python -m examples.boom_cost_model.prepare_gcc \
  --host-root /your/compiler-build-mount/boom-gcc \
  --worker-root /tmp/spec_build/boom-gcc \
  --worker your-compiler-container
```

Host and worker paths must refer to the same existing bind mount. No compiler
is installed over the original. Candidate prefixes contain copied frontends
and wrappers around the original drivers using `-B`; the original target
libraries, assembler and linker remain in use. Each snapshot records frontend
and wrapper hashes, source revision, configure command and build log.

## Configuration and launch

Keep the machine-specific JSON configuration and results private. Required
fields are `gcc_root` (worker path), `baseline_prefix` (worker path),
`hardware_manifest` (controller path to the verified matching driver manifest),
`benchmarks` (`["605.mcf_s", "648.exchange2_s"]`), `model`, `iterations` (1..20),
`repeats` (1..5), `min_improvement` (0..0.1), `final_ref` (boolean), `aws_profile`,
`aws_account`, `iam_user`, `region`, `instance_id`, `ssh_alias`,
`security_group_ids`, and `approved_network_policy` (mapping group IDs to
their approved `IpPermissions` and `IpPermissionsEgress`). Use the site's
previously audited network policy; do not widen it to make a run work.

```bash
# Source your site's existing private environment first (Ray address/auth/guard).
python -m examples.boom_cost_model.optimize \
  --config /private/experiment.json --run-dir /private/results/experiment \
  --prepare-only

python -m examples.boom_cost_model.optimize \
  --config /private/experiment.json --run-dir /private/results/experiment
```

The normal launch discovers the current F2 address with AWS, verifies the IAM
identity, security-group policy and available AGFI, then checks strict SSH and
GatewayPorts=no. Reconnect the site's existing worker tunnels if the address
changed or its worker is offline. `--prepare-only` needs no AWS or Claude call.

The unmodified rebuild must first reproduce C/C++/Fortran smoke assembly and
static linking, then baseline and rebuilt SPEC test workloads must pass QEMU
and native `specinvoke -E` output comparison. These smoke comparisons are a
gate, not a proof that the rebuilt host executables are byte-identical.

The FPGA baseline always uses the **original installed compiler**. Claude
proposes only JSON integer costs; built-in tools and permission bypass are
disabled. Deterministic code edits only the cost fields in `rocket_tune_info`.
The revision, scheduler, ISA, ABI, pinned Speckle flags and one-thread setting
stay fixed. Each candidate must pass test inputs in QEMU before train inputs
run on F2. Benchmark, job and collection exit codes and native comparisons must
all succeed. QEMU timings never enter the objective.

Selection uses geometric mean speedup against the same original-compiler train
baseline, with median guest RealTime across repetitions. One repetition is an
exploratory measurement; increase repetitions before interpreting small gains.
When `final_ref` is true, run baseline and the selected winner on held-out
reference inputs after proposal selection ends. Reference results never return
to Claude. Infrastructure/authentication failures stop the controller and save
a traceback; invalid proposals and incorrect candidates provide failure feedback.

Use the same command and run directory to resume. Configuration changes require
a new directory. A controller lock prevents two processes sharing one experiment.
All workload archives, build metadata, raw outputs, UART/manager logs, native
comparisons, prompts, proposals, failures and timing summaries stay in the private
run directory. Detailed SPEC compiler logs also stay in the existing FireMarshal
image store under `<descriptor>-build-logs`. No SPEC assets belong in Git.

## Subsequent experiments

Single-job subsets may also include `600.perlbench_s`, `602.gcc_s`,
`623.xalancbmk_s`, `625.x264_s`, `631.deepsjeng_s`, and `641.leela_s`.
Every selected workload still needs new baseline/rebuilt QEMU correctness gates.
Set `qemu_memory_mb` (2048..12288) for workloads needing more guest memory.
OMNeT++ remains excluded pending its compiler compatibility fix; multi-job XZ
requires explicit per-case accounting before inclusion.

`prior_runs` is a list of private experiment directories. The controller imports
only original-baseline and candidate **train** times and cost tables from the
same compiler/hardware, plus executable identity comparisons. It does not import
reference results or previous model rationales. These observations provide
context; the new subset receives its own baseline and measurements. Small
differences from a single run do not establish optimal parameter values.
Optional `seed_proposals` contains bounded proposals in the same JSON format as
Claude responses. Remaining iterations use the authenticated Claude CLI.

The default `search_mode: "costs"` preserves scheduling. A separate
`search_mode: "issue-rate"` requires proposals with
`"scheduling": {"issue_rate": 2}` (integer 1..8), baseline `costs`, and a
`rationale`. It changes only GCC's issue-rate hook. Generic scheduler pipeline
reservations and latencies remain fixed: this is not a full BOOM scheduling
model. Compare against the original compiler rather than relabeling a changed
compiler as baseline. Keep ISA/ABI and instruction flags unchanged.

For multiple independently prepared F2 workers, set `fpga_workers` to a list of
`instance_id`, `ssh_alias`, and `ray_address` mappings. Each instance must retain
the approved security-group policy, trusted SSH identity, localhost listeners,
and the exact verified FPGA image/driver. The controller checks SSH/IMDS/Ray
identity and refuses an active driver. Benchmark jobs dispatch concurrently
with hard node affinity; benchmark-to-worker pairing stays fixed across
compilers. Separate controllers should run sequentially over the pool.

`small_images: true` limits each image to its benchmark. Before FPGA dispatch,
the controller hashes the read-only filesystem's complete contents, modes,
ownership, links, boot binary and job settings. The audited guest wrapper does
not execute native `compare.cmd`/`speccmds.cmd`; only their selected build-host
compiler location in `-E PATH`/`-E RISCV` is canonicalized using the workload's
compiler provenance. Raw hashes remain recorded. This exception is disabled
if the guest wrapper differs from its audited hash. All benchmark commands,
inputs, other environment entries and comparison tolerances stay exact.
Validated identical samples can
be reused only with matching runtime/hardware, physical instance, input size
and repeat index. Reused records explicitly say they are not independent
measurements. All independent repeats still execute. Conservative cache misses
are expected when any runtime file or metadata content changes.

Set `train_timeout_seconds` and `ref_timeout_seconds` explicitly (up to seven
days); reference defaults to 72 hours. Timeout logs retain captured stdout,
stderr and available UART. A detached driver can remain active after manager
timeout: preserve its image, inspect progress, and collect/validate its eventual
outputs before retrying. A timeout never counts as a correct measurement.

FireSim also stages a separate raw rootfs image for each job, and keeps a
transfer copy under `sim_slot_0/rsyncdir`. Reusing one AGFI does not reuse
these disk images. After a successful job, this example makes only that job's
staging images sparse again and checks their content hashes. If setup fails
before the job finishes, inspect disk space and active FireSim processes before
reclaiming idle staging images. Restart with the same configuration and run
directory: completed candidates and the interrupted candidate's saved proposal
are reused. An infrastructure failure does not produce a candidate score.

Prepare the independent add/multiply/divide dependency and throughput probes:

```bash
python -m examples.boom_cost_model.prepare_probes \
  --config /private/experiment.json --run-dir /private/results/probes
```

This builds with the original pinned compiler and checks six cases in QEMU.
It does not run on an FPGA. Both RISC-V and native timings use monotonic
nanoseconds. They include loop/timer overhead and must not be treated as exact
instruction latencies. Run the saved artifact on verified matching hardware,
check its six checksums and guest exit status, and record hardware provenance
before using its elapsed times to guide a separate scheduling experiment.
