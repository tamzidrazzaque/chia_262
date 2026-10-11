# Probe-derived BOOM model and remaining workloads

This experiment adds unsigned-integer FIR, matrix multiplication, and pointer
chasing. It also derives a small hardware cost model from fixed instruction
probes, then checks cycle predictions on held-out FIR/matrix cases. The model
is an external predictor; it does not install a new GCC or LLVM backend tune.

## Experimental design

FIR computes 32, 128, or 512 outputs with 8 or 32 variable coefficients.
Matrix multiplication uses row-major matrices of dimensions 4, 8, and 16 with
straightforward i/j/k loops. All arithmetic is unsigned 32-bit, with defined
wraparound, making correctness checks exact. References traverse axes in a
different order. Every output element and checksum are checked after warm-up
and measurement. This is scalar integer arithmetic, not a floating-point DSP
or vector study.

Pointer chasing follows a fixed-seed shuffled cycle with one node per 64-byte
cache line. Footprints are 256 bytes, 16 KiB, and 64 KiB; one or four independent
chains perform a total of 1,024 index loads per call. Four chains start at
equally spaced positions around the same cycle. Warm-up touches all nodes for
every case. Medium BOOM's configured L1 data cache is 16 KiB (64 sets, four ways,
64-byte lines), so the largest case tests behavior beyond L1. The base Chipyard
configuration includes a 512 KiB inclusive last-level cache, which this
footprint fits. These are warmed accesses, not a controlled cold-cache/DRAM
experiment. Starting indices are
restored between timed calls; that small common reset is included in timings.

Each workload is compiled with GCC 15.2 at `-O3`, using Rocket, generic-ooo, or
Xiangshan Nanhu tuning. ISA/ABI, runtime, and harness stay fixed. There are
three samples of two calls per tune and case, with rotated execution order.
Three link layouts balance code addresses. Workloads produce 405 samples.

## Hardware characterization

Four probes force exact RISC-V operations with inline assembly: `mulw` by 13;
four shift/add instructions implementing the same multiplication; `addiw`;
and cached dependent `ld` through a 512-byte pointer cycle. One or eight
independent states perform 128 or 512 total operations. Blocks contain 32
operations so branch overhead is small. GCC cannot replace the forced
operation sequence. All three tunes are still compiled to expose variation
in surrounding code; no tune-specific parameter is learned.

Checks use exponentiation by squaring for multiplication, a closed form for
addition, and independently computed pointer positions. Native HOST_CHECK
tests validate references; Spike checks the actual RISC-V instruction probes.
Only BOOM `mcycle` measurements fit the model. Probes produce 432 samples.

The fitter calculates `(cycles_512 - cycles_128) / (2 * (512 - 128))` to
remove fixed overhead, then takes the median across three placements and
three surrounding tune variants. Width one estimates effective chain cost;
width eight estimates sustained cycles per operation with eight independent
chains. These include a small repeated-block loop contribution. They are not
guaranteed peak throughput or directly interchangeable with GCC scheduler
latency fields.

The observed operation costs were approximately:

| Operation | Dependent chain cycles/op | Eight-chain cycles/op |
| --- | ---: | ---: |
| `mulw` | 6.01 | 1.00 |
| Multiply by 13 using shifts/adds | 4.00 | 2.10 |
| `addiw` | 1.01 | 0.55 |
| Cached `ld` | 4.00 | 1.05 |

The model estimates multiplication cost as the maximum of chain cost divided
by available parallelism and measured sustained cost. It prefers shifts/adds
with one or two independent chains and multiplication with four or eight.
That is consistent with the previous dataflow experiment, which is a sanity
check, not a newly blinded validation dataset.

## Held-out evaluation

`hardware_model.py fit` reads only probe logs. It freezes a JSON model with
the implementation hash, training fingerprints, compilers, simulator, and UTC
timestamp. It refuses to overwrite an existing model. FIR and matrix timing
results are read afterward by `validate`; no parameter is adjusted using them.
Exact sources and disassembly are archived separately from timing reports.

The predictor extracts the innermost multiply loop and enclosing loop spans
from linked assembly. Known loop trip counts estimate dynamic instruction,
multiply, and load/store counts. It takes the maximum of issue, multiply,
memory, and accumulator bounds, using measured add/load/multiply costs.
Enclosing-loop counts approximate control paths and setup. This first model
omits detailed dependency scheduling, cache misses, branch mispredictions,
and register pressure. It refuses unsupported loop shapes. Pointer chasing
is compared across tunes and chain counts, not included in this cached MAC
prediction model.

The generated validation report records signed errors and mean absolute
percentage error. Prediction accuracy is a separate claim from compiler
speedup: these runs do not demonstrate an improvement from a newly integrated
compiler cost model.

## Reproduction

Use the isolated CHIA Python environment and toolchain paths described in
[README.md](README.md). Set `CHIPYARD_DIR` and `RISCV_GCC` accordingly. The
following runs sequentially; independent simulations may run concurrently.

```bash
for profile in probes workloads; do
  for layout in 0 1 2; do
    python examples/boom_cost_model/run_$profile.py \
      --gcc "$RISCV_GCC" \
      --runtime-gcc "$CHIPYARD_DIR/.conda-env/riscv-tools/bin/riscv64-unknown-elf-gcc" \
      --simulator "$CHIPYARD_DIR/sims/verilator/simulator-chipyard.harness-MediumBoomV3Config" \
      --dramsim-ini "$CHIPYARD_DIR/generators/testchipip/src/main/resources/dramsim2_ini" \
      --opt O3 --layout "$layout" --timeout 7200 \
      --out "outputs/boom_cost_model/expanded/$profile/medium-layout$layout"
  done
  python examples/boom_cost_model/prepare_runs.py \
    --runs "outputs/boom_cost_model/expanded/$profile" \
    --objdump "$CHIPYARD_DIR/.conda-env/riscv-tools/bin/riscv64-unknown-elf-objdump"
done
python examples/boom_cost_model/hardware_model.py fit \
  --runs outputs/boom_cost_model/expanded/probes \
  --model outputs/boom_cost_model/expanded/medium_boom_model.json
python examples/boom_cost_model/hardware_model.py validate \
  --runs outputs/boom_cost_model/expanded/workloads \
  --model outputs/boom_cost_model/expanded/medium_boom_model.json
python examples/boom_cost_model/summarize_workloads.py \
  --runs outputs/boom_cost_model/expanded/workloads
```

Fitting remains independent of workload timings even if workload simulation
finishes first. For a fresh calibration, use a new output root and model path.
Preserve `sources/` before changing source files; `prepare_runs.py` refuses
to archive a source that no longer matches the compilation fingerprint.

All reports and raw artifacts are under `outputs/boom_cost_model/expanded/`.
Tests use the existing `tests/` discovery command in the example README.

## Completed Medium BOOM results

All six runs passed full-output correctness checks (837 timing samples total).
Xiangshan tuning gives a 1.0169x FIR speedup versus Rocket, but matrix
multiplication averages 0.9310x; generic out-of-order tuning is nearly flat.
The probe-only frozen model predicts held-out FIR/matrix cycle counts with
7.1% mean absolute percentage error, with about 23% worst-case error.
All predictions match those saved before validation. This evaluates an
external predictor, not a modified compiler backend or a demonstrated
compiler speedup. Detailed results and plots are in
`outputs/boom_cost_model/expanded/SUMMARY.md`.
