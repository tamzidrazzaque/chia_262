# Rocket vector target feasibility

## Status

**Bare-metal Saturn RVV execution is verified; this is not yet a measured
experiment.** RVV intrinsic code generation and `zvbb` assembly pass. Saturn
`MINV128D64RocketConfig` successfully elaborates to FIRRTL and Verilog, and a
self-checking `vadd.vv`/`vandn.vv` program passes on its Verilator model. The
functional probe uses a one-hart test config with the same Rocket/Saturn vector
parameters, a test-only boot ROM, and direct `+loadmem` ELF loading. It verifies
those instructions and data results, not the normal boot ROM, an OS/runtime,
application compatibility, or performance. The installed Spike executable
traps on `vsetivli`, so it is not a suitable functional oracle. No vector
FireSim image, matching driver, or vector application run has been verified.
No hardware was launched. A compiler audit found that the installed GCC 13.2.0
does not vectorize even a simple integer-add loop under explicit vectorization
flags. The intrinsic smoke does not establish a viable automatic-vectorization
cost-model baseline.

**Direction updated on 2026-11-04:** use upstream
`REFV256D128RocketConfig` (VLEN 256, DLEN 128) and its
`FireSimREFV256D128RocketConfig` wrapper as the active target. This replaces
the earlier MINV128D64 selection so the campaign follows the Saturn
configuration supported by upstream FireSim. The official catalog provides
AGFI `agfi-012e92467d7d2149a`, its F2 recipe, and pinned source revisions. It
does not publish a `driver_tar`; the exact driver must be built and accepted
from those pins. See `SATURN_FIRESIM.md` and `saturn-firesim-discovery.json`.
Ara remains outside the active campaign.

**Loop-A preparation update on 2026-11-04:** the real unchanged-SPEC
`648.exchange2_s` test workload now builds and passes SPEC validation for the
scalar role, the stock GCC 15.1 RVV role, and the first bounded Saturn-aware
cost candidate. The candidate changes the final application ELF, so the
compiler-cost hook is feasible for this workload. This remains correctness and
static code-generation evidence only; the CHIA result has no Saturn timing
backend and makes no speedup claim. See [the roles 1-3 status](ROLE_123_STATUS.md).
Because that run used QEMU VLEN 128 metadata, it is retained as feasibility
evidence and must not be reused as the frozen VLEN 256 baseline.

The current scalar Rocket target remains separate. Its documented
`RocketConfig`, `rv64imafdc` toolchain, image discovery, and driver evidence do
not establish vector support.

## Source-level options reviewed

The following configuration definitions were inspected in the installed
container's source tree. These facts establish source-level Rocket integration
only.

| Candidate | Source revisions in installed container | Rocket configuration and parameters | Status |
|---|---|---|---|
| Ara | Chipyard `ad07481af487c44c9f0545db39f9c16cabdecc77`; Ara `96daf15d3c54ac4975ea2bdc869f95bccdf90a1e` | `V4096Ara2LaneRocketConfig`; `WithAraRocketVectorUnit(4096, 2)` and one `Rocket` core | Source-level comparison only; outside the selected Saturn campaign |
| Historical Saturn probe | Chipyard `ad07481af487c44c9f0545db39f9c16cabdecc77`; Saturn `2dae15d16bebe10f413ea39bdd18aa402eb419dd` | `MINV128D64RocketConfig`; `WithRocketVectorUnit(128, 64, VectorParams.minParams)` and one `Rocket` core | Elaboration and bare-metal RVV+Zvbb pass; no longer the active measurement target |
| Active Saturn target | Build source: Chipyard `19a07f6b8d4d1db81f5561d9aeceb2cdc43407fe`; FireSim `b7927ea504c501194eaec3e993c415f2270170f8`; Saturn `dfe75de2a8868d51d42c20612821431a9fcf645e`; Rocket Chip `55bcad0f59436de98ea510334121de8546b9e9d7`. Catalog publication: Chipyard `f503763b0c702ac3c423e58d8cc9d0975796a8c2` | `REFV256D128RocketConfig`, VLEN 256/DLEN 128; `FireSimREFV256D128RocketConfig`; AGFI `agfi-012e92467d7d2149a` | AWS metadata and source history reconciled; locally built matching driver, Linux/SPEC execution and timing remain unverified |

The installed container also has Rocket Chip `2f1c549d061f7d6e7fd209ff8b322d0940d200b6`.
The container image used was `ghcr.io/ucb-chia/chia-chipyard:latest`, with local
image ID `sha256:bee6497fe1a35b178421d25d9c0ed647eeb09ee8c9e3a1f3c6c90105b68bc52c`
and registry RepoDigest
`ghcr.io/ucb-chia/chia-chipyard@sha256:f983966b1cdc1f6c22ab87d276e1ceb5711d73f6e0bb84a8f5a6b2cbf2b9758c`.
The branch uses these installed revisions as a separate feasibility
environment, not as the scalar handoff's source pins.

Source references for the installed submodule revisions:

- [Ara Rocket configuration](https://github.com/ucb-bar/ara-wrapper/blob/96daf15d3c54ac4975ea2bdc869f95bccdf90a1e/chipyard/AraConfigs.scala)
- [Saturn Rocket configurations](https://github.com/ucb-bar/saturn-vectors/blob/2dae15d16bebe10f413ea39bdd18aa402eb419dd/chipyard/SaturnConfigs.scala)
- [Saturn Rocket vector-unit mixin](https://github.com/ucb-bar/saturn-vectors/blob/2dae15d16bebe10f413ea39bdd18aa402eb419dd/src/main/scala/rocket/Configs.scala)
- [Current scalar target notes](TARGET_NOTES.md)
- [Existing image discovery record](image-discovery.json)

The Saturn mixin installs `SaturnRocketUnit`, an early vector decoder, and
declares `zvbb` in `vExts`. This is a source fact, not a complete compiler
target profile or proof that a built binary will execute on an image. The Ara
configuration uses a different vector-unit integration and much larger
configured vector length. Do not compare their performance or compiler labels
as if they were the same hardware.

The source review found no Rocket+Hwacha configuration or Hwacha submodule in
the inspected Chipyard integration. This is not a claim that Hwacha
cannot be integrated in another source tree; it means no current evidence
supports choosing it for this branch.

## First implementation probe

Saturn `MINV128D64RocketConfig` was selected for the first elaboration and
functional probe but is no longer the active configuration for the campaign.
It combines one Rocket core with a 128-bit vector length and 64-bit data width.
Saturn's source declares `zvbb`, and the tested GCC
supports the smoke program's required ISA flags. The elaboration and
instruction-level functional gates now pass with the test-only boot setup
described below. This historical probe does not establish claims for the
active REFV256D128 FireSim target.

## Current checkout and evidence gaps

- The top-level `.gitmodules` does not stage Chipyard, Ara, or Saturn. The
  existing `ghcr.io/ucb-chia/chia-chipyard:latest` container contains the
  source and the selected feasibility target. This branch explicitly uses the
  installed combination above; it is separate from the scalar handoff pins.
- [`image-discovery.json`](image-discovery.json) records only scalar
  `RocketConfig` and `QuadRocketConfig` F2 images. Neither is a vector target;
  their driver and matching-source evidence are unset/unverified.
- The inherited scalar compiler setup targets `rv64imafdc`/`lp64d` and disables
  vectorization for its scalar workload. The existing
  `ghcr.io/ucb-chia/chia-chipyard:latest` container has GCC 13.2.0, Java 20,
  sbt, and Verilator after sourcing `env.sh`. GCC
  `gc891d8dc23e` has SHA-256
  `28b629f64ed9797dc198621eb5cfcb63c0a48e17b95c639bada20f14038e77e4`.
  `vector_compile_smoke.c` compiled with `-march=rv64gcv -mabi=lp64d`; its
  object contains `vsetvli`, `vle32.v`, `vadd.vv`, and `vse32.v`, and advertises
  V 1.0 in ELF attributes. `vector_zvbb_smoke.S` assembled `vandn.vv` with
  `-march=rv64gcv_zvbb`; its ELF attributes advertise `zvbb1p0` and `zvkb1p0`.
  This verifies intrinsic code generation only, not automatic vectorization,
  a complete target sysroot/runtime, or execution on Saturn/Ara.
- An independent audit compiled a restricted-pointer `int` array-add loop with
  the installed GCC 13.2.0 using `-O3 -ftree-vectorize -fopt-info-vec-all
  -march=rv64gcv_zvbb -mabi=lp64d`. GCC reported `couldn't vectorize loop` and
  `relevant stmt not supported`, emitted `vectorized 0 loops`, and generated
  scalar `lw`/`addw`/`sw` code. This probe does not characterize every loop,
  but it blocks the assumption that this compiler is an automatic RVV
  vectorization baseline. [GCC 14's release notes](https://gcc.gnu.org/gcc-14/changes.html)
  say RISC-V loop and SLP vectorizers were enabled in that release. Select and
  pin a rebuildable compiler that demonstrably vectorizes the chosen workload
  before attempting vectorization cost-model edits.

  The probe source was `void add(int *restrict d, const int *restrict a,
  const int *restrict b, long n) { for (long i = 0; i < n; ++i) d[i] = a[i]
  + b[i]; }`. It was compiled to assembly from stdin with the installed
  container's `riscv64-unknown-linux-gnu-gcc` using those flags and `-S -o -`.
- The inherited `chia/chipyard/cost_model.py` and
  `examples/rocket_cost_model/prepare_compiler.py` pin GCC 13 and a scalar
  `rv64imafdc` build. `build_candidate.py` edits scalar `rocket_tune_info`
  fields. These provide implementation patterns, not a vector compiler builder
  or evidence that a vector cost dimension changes generated code.
- Existing Rocket application preparation, hardware guards, and FireSim runner
  are bound to the scalar image. They must not be pointed at Ara/Saturn by
  changing a label or one manifest field.
- No matching vector FireSim build recipe, FPGA image, generated driver,
  vector runtime/OS support check, vector application baseline, or target
  timing evidence is recorded.

## Saturn elaboration

The Saturn elaboration command was attempted from
`/home/ray/chipyard/sims/verilator`, after sourcing
`/home/ray/chipyard/env.sh`:

```text
make verilog CONFIG=MINV128D64RocketConfig
```

The first attempt could not resolve SBT plugin dependencies because bridge
network DNS failed. Retrying with host networking resolved the dependencies;
SBT completed and `make verilog` exited successfully. FIRRTL and generated RTL
are retained under `.vector-validation/saturn-design/` (ignored by Git). The
FIRRTL includes Saturn vector modules, and the generated device tree advertises
`zvbb` and `zvl128b`. Hashes and exact source revisions are recorded in the
local `elaboration-manifest.txt`.

A second, artifact-retaining invocation copied the generated files before its
metadata-capture step exited with Git's dubious-ownership error in the
container. This did not invalidate the earlier successful `make verilog` run
or the copied outputs; no global Git configuration was changed.

The installed Spike 1.1.1-dev traps on its first `vsetivli` even when asked to
enable `rv64gcv_zvbb`; that Spike build is not a functional oracle. The default
one-hart boot-ROM path also did not reach the payload: its startup code waits
for additional harts. `+loadarch` is not supported by this Verilator harness,
which uses TSI. For the bounded instruction probe, a temporary
`SingleHartSaturnSmokeConfig` retained one Rocket core and Saturn's
`WithRocketVectorUnit(128, 64, VectorParams.minParams)` mixin, overriding only
the boot ROM with a jump to `0x80001000`. The run used
`+loadmem=/out/vector-loadmem.elf` so simulated DRAM contained the ELF before
the jump; without it, the core reached the payload address before memory was
ready. The payload enables `mstatus.VS`, runs `vsetivli`, vector loads, `vadd.vv`,
`vandn.vv`, and vector stores, then checks every result and signals success via
`tohost`. Verilator reported `*** PASSED ***` after 4,126 simulation cycles.
The final ELF SHA-256 is
`9360df232984f7251bca4563fbdd9f767f455619740a434a752e1260f99383de`.
Inputs, ELF, successful simulator binary, logs, and generated collateral are
under the ignored `.vector-validation/` directory. This proves only the tested
bare-metal instruction path; normal boot, a target OS/runtime, and real
applications remain open.

The payload sets `vl=4` for four 32-bit elements at `LMUL=1`, which fills the
128-bit vector register exactly. It does not exercise strip mining, tail or
mask behavior, multiple element widths or LMULs, faults, or vector-state
preservation across a context switch. The next functional program should cover
the modes that the selected application actually uses.

The retained FIRRTL/RTL under `saturn-design/` belongs to
`MINV128D64RocketConfig`; the passing simulator binary belongs to
`SingleHartSaturnSmokeConfig`. Its Scala definition, boot ROM, binary and run
log are retained, but a separately generated RTL snapshot and build manifest
for that exact test config are not present in the local validation directory.
Retain those if this harness becomes the application measurement target.

## Work log

All project edits, smoke-test sources, logs, and object files from this work
are under `/scratch/trazzaque/Corey`. The listed teammate repositories,
private SPEC installation/license files, FireMarshal data, and Docker helper
paths were inspected only as needed to locate the environment; none was
modified. No images were rebuilt, teammate containers were left untouched, and
no hardware was accessed.

1. Located the existing Chipyard container image and confirmed that its pinned
   source tree includes the Ara and Saturn generators. The host-side
   `/home/eecs/trazzaque/chipyard` symlink points to a missing path; no host
   Chipyard checkout was created.
2. Recorded the local image ID, registry RepoDigest, and Chipyard, Rocket Chip,
   Ara, and Saturn revisions above. Used isolated disposable containers for
   checks; the active teammate containers were left running and untouched.
3. Added `vector_compile_smoke.c` and `vector_zvbb_smoke.S` in this branch.
   Using the installed Chipyard container's GCC 13.2.0, successfully compiled
   the RVV intrinsic source and assembled the `zvbb` `vandn.vv` instruction.
   Confirmed emitted instructions and ELF architecture attributes. These
   checks establish compiler/assembler code generation only.
4. First attempted elaboration while mounting the whole Corey directory. The
   container could not write the log because of host/container UID permissions;
   the command was stopped and this attempt did not produce evidence. Retried
   with only the local `.vector-validation/` directory mounted writable.
5. Retried with host networking after the bridge-network DNS failure. SBT
   resolved its plugins, and `make verilog CONFIG=MINV128D64RocketConfig`
   completed successfully. The generated FIRRTL, Verilog collateral, and logs
   are retained in `examples/rocket_cost_model/.vector-validation/`.
6. Verified generated Saturn vector modules in FIRRTL and `zvbb`/`zvl128b` in
   the generated device tree. A later metadata-capture step hit Git's
   dubious-ownership guard inside the disposable container after copying the
   generated files; no global Git settings were changed.
7. Built and ran a self-checking `vadd.vv` and Zvbb `vandn.vv` bare-metal test.
   The initial default-boot attempt stayed in the single-hart boot-ROM path;
   the installed Spike build also traps on `vsetivli`. A temporary boot ROM
   reached the ELF but required direct `+loadmem` initialization before the
   jump. The first vector run then exposed that the test had not enabled
   `mstatus.VS`; after enabling it, the trace showed the test's `vandn` operands
   were reversed and its signed `lw` checks did not match unsigned vector data.
   Correcting the operand order and using `lwu` made the complete self-check
   pass. The successful run executed through the final tohost completion after
   4,126 simulated cycles. Logs for the failed and successful iterations are
   retained under `.vector-validation/`.

## Next feasibility actions

1. Select the compiler research path. For automatic vectorization, pin and
   verify a compiler that vectorizes both a simple loop and relevant application
   code; the installed GCC 13.2.0 did not pass the simple-loop probe. For an
   explicit-intrinsics application, first show a bounded compiler model edit
   changes its final machine code. Stop the cost-model search if neither path
   has code-generation sensitivity.
2. Retain an exact simulator target manifest and generated RTL for the Saturn
   configuration that will run the application. Verify its vector parameters,
   build requirements, virtual-memory behavior and Linux software path before
   accepting it as the SPEC target; the current instruction pass is narrower.
3. Check authorized SPEC CPU2017 access and prioritize the BOOM handoff's
   `648.exchange2_s` test/train inputs. Reuse
   `examples/spec_build/spec_sw_build_loop.py:start_workload`, the existing
   QEMU test stage, and native SPEC output comparison. The scalar Rocket
   handoff records paused SPEC access. Pin compiler, assembler, linker,
   sysroot, ABI, vector extensions and runtime; inspect the final ELF and
   verify that the Linux guest preserves vector state. If Exchange2 stays
   scalar, retain it as a shared workload and screen another licensed SPEC
   application for hot RVV code before vector-cost tuning. The current
   bare-metal boot-ROM test cannot serve as the SPEC runtime.
4. Pilot a bounded SPEC application test on exact Saturn RTL and record wall
   time per simulated target cycle. Full train runs on Verilator require a
   practical runtime estimate. Otherwise, investigate a matching vector
   FireSim design, image, driver and worker, following the handoff's F2 path.
   Every timing backend needs its own exact-target preflight and application
   baseline; QEMU correctness time is not a target performance observation.

Stop and report a blocker if a candidate cannot pass its source/build, compiler,
or functional gate. Do not start a search until a real vector application is
correct on an exact, pinned RTL simulator or physical target and a repeatable
baseline establishes the measurement protocol. Report simulator cycle results
as simulator results; physical-target claims need a separately verified matching
image, driver, and worker.
