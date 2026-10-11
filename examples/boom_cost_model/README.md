# BOOM GCC tuning experiment

Compare existing GCC RISC-V tunes before proposing a new cost model. The static
comparison in `compare_cost_models.py` inspects source cost tables and emitted
assembly. `run_timing.py` measures compiled kernels on a Chipyard RTL simulator.
GCC must support `rocket`, `generic-ooo`, and `xiangshan-nanhu`; the local
Chipyard GCC 13.2 does not support the latter two. The initial experiment uses
the prebuilt xPack GCC 15.2 toolchain, without rebuilding GCC.

## Cycle measurement

Build a simulator using the existing Chipyard environment:

```bash
source /path/to/chipyard/env.sh
make -C /path/to/chipyard/sims/verilator CONFIG=SmallBoomV3Config -j2
```

Then activate CHIA's Python environment and run:

```bash
conda activate chia_env
unset PYTHONPATH
export PYTHONNOUSERSITE=1
python examples/boom_cost_model/run_timing.py \
  --gcc /path/to/gcc15/bin/riscv-none-elf-gcc \
  --runtime-gcc /path/to/chipyard/.conda-env/riscv-tools/bin/riscv64-unknown-elf-gcc \
  --simulator /path/to/chipyard/sims/verilator/simulator-chipyard.harness-SmallBoomV3Config \
  --dramsim-ini /path/to/chipyard/generators/testchipip/src/main/resources/dramsim2_ini \
  --opt O2 \
  --out outputs/boom_cost_model/timing/boom-O2
```

Repeat with `--opt O3` and a different output directory. The runtime compiler
provides Chipyard's HTIF startup and libraries. It builds the harness once with
fixed `-O2 -mtune=rocket` flags; only the separately compiled kernels vary.
There is no LTO. All variants use `-march=rv64gc -mabi=lp64d -mcmodel=medany` and
64-byte function alignment. Assembly from the earlier comparison can differ in
alignment or addressing directives because these binaries target bare-metal
execution at Chipyard's DRAM address.

The single binary contains all three variants. Each sample warms the selected
kernel, measures eight calls over 128 elements using the simulated hart's
`mcycle` counter, and validates the returned values. Input integers are bounded
to avoid signed overflow; floating-point values are exactly representable
binary fractions. SAXPY inputs are reset before measurement. Six samples rotate
the execution order so each tune occupies each order position twice. Printing
happens after every measurement. Fences and compiler memory barriers surround
counter reads. Common counter, caller, and loop overhead is included, rather
than subtracted. These are target cycle counts, not host simulator wall times.

Outputs include the complete simulation log, per-sample cycles, medians, speedup
relative to Rocket, and metadata with compiler versions, build commands, and
source/binary/simulator hashes. Failed simulation, incorrect output, duplicate
samples, missing samples, or nonpositive counts prevent reporting a speedup.

This is an initial warm-cache experiment on one core configuration and one
input pattern. It does not establish performance on a larger BOOM, cold caches,
different data, or SPEC. Tiny differences can reflect instruction placement or
branch predictor state. Identical kernels provide useful controls. Broader
evaluation should vary inputs, lengths, code placement, and target configuration
before moving to SPEC on FireSim. CHIA orchestration is not needed for this
single-machine measurement, but can automate the same compile/run commands.

## Initial local result

On `SmallBoomV3Config` (Chipyard revision `bcb61291`), GCC 15.2 produced the
following median cycle counts. Both `-O2` and `-O3` runs produced the same
measurements, and all correctness checks passed. These are six samples of eight
calls, with 128 elements per call, on the input pattern in `timing.c`.

| Kernel | Rocket cycles | Generic OOO cycles | Xiangshan Nanhu cycles |
| --- | ---: | ---: | ---: |
| branchy | 8652.5 | 8614.5 | 7982.5 |
| int_mix | 13069 | 12645 | 12644.5 |
| dot | 7316 | 7315.5 | 7316.5 |
| saxpy | 7403.5 | 7374 | 7403 |

The two out-of-order tunes deliver approximately 1.034x speedup for `int_mix`;
Xiangshan delivers approximately 1.084x for `branchy`. Generic OOO's branchy
result and floating-point differences are below 0.5%, with overlapping sample
ranges, and should not be treated as meaningful gains. Branchy has more sample
variation than int_mix. The observed gains apply to this small BOOM and input,
not to all BOOM implementations or applications. Small BOOM here has a
one-instruction decode width and a 32-entry reorder buffer.

The full logs, ranges, binaries, and metadata are in
`outputs/boom_cost_model/timing/boom-O2/` and `boom-O3/`. Future experiments should
check sensitivity to input and code placement, then evaluate a larger BOOM and
SPEC on FireSim.

## Input, placement, and core sensitivity

`--suite` measures sizes 32, 128, and 512 with four bounded integer patterns:
the original stride-based mix, all values in the middle branch, all values in
the high branch, and a mixed pattern from a fixed-seed linear congruential
generator. Floating-point inputs remain fixed for each size, providing controls
while integer inputs change. All working sets still fit in the data cache;
this suite does not test cold-cache or large-memory behavior.

The suite uses two calls per timed sample and three samples, rotating execution
order once through all positions. `--layout 0`, `1`, and `2` rotate the linked
tune order within each kernel. Each tune then occupies the same three code
addresses, which are recorded in metadata and checked when summarizing. Output
is buffered after all measurements to reduce HTIF console overhead. Target
cycles still include common counter and caller overhead, particularly relevant
for the shortest input size.

Build `MediumBoomV3Config` as well as Small BOOM. Medium BOOM has decode width
two and a 64-entry reorder buffer, compared with Small BOOM's width one and
32 entries. With `CHIPYARD_DIR` and `RISCV_GCC` set to the existing Chipyard
checkout and experimental compiler, reproduce the six runs with:

```bash
for core in small medium; do
  if [ "$core" = small ]; then config=SmallBoomV3Config; else config=MediumBoomV3Config; fi
  for layout in 0 1 2; do
    python examples/boom_cost_model/run_timing.py \
      --gcc "$RISCV_GCC" \
      --runtime-gcc "$CHIPYARD_DIR/.conda-env/riscv-tools/bin/riscv64-unknown-elf-gcc" \
      --simulator "$CHIPYARD_DIR/sims/verilator/simulator-chipyard.harness-$config" \
      --dramsim-ini "$CHIPYARD_DIR/generators/testchipip/src/main/resources/dramsim2_ini" \
      --suite --opt O3 --layout "$layout" --timeout 3600 \
      --out "outputs/boom_cost_model/sensitivity/$core-layout$layout"
  done
done
python examples/boom_cost_model/summarize_suite.py \
  --runs outputs/boom_cost_model/sensitivity
```

This produces 2,592 cycle samples across two cores, twelve input cases, three
code placements, four kernels, and three tunes. The summary revalidates raw
logs and rejects missing cases, mismatched sources/compilers/simulators, or
unbalanced code addresses. It reports a geometric mean across placements for
each case, then an equally weighted geometric mean across twelve input cases.
This is a sensitivity summary, not a SPEC score or an application-weighted
performance claim. A descriptive count of cases faster by more than 1% in
every layout is included; that threshold is not a significance test.

The full RTL suite can take tens of minutes per binary on this host. The
wall-clock timeout controls how long to wait for execution; it is separate from
the measured target cycle counts. Independent runs can execute concurrently
when the host has enough CPU and memory. A Spike execution of the suite also
passed every correctness check, but its instruction counts are not used as
BOOM performance measurements.

Historical source snapshots for the initial fixed-input experiment are saved
as `outputs/boom_cost_model/timing/initial-timing.c` and `initial-run_timing.py`.

### Measured sensitivity results

All six runs passed correctness checks, producing 2,592 cycle samples. Relative
to Rocket, the equally weighted geometric mean speedups were:

| Kernel and tune | Small BOOM | Medium BOOM |
| --- | ---: | ---: |
| Integer mix, generic-ooo | 1.0375x | 1.0000x |
| Integer mix, xiangshan-nanhu | 1.0355x | 1.0000x |
| Branch-heavy, generic-ooo | 1.0094x | 1.0058x |
| Branch-heavy, xiangshan-nanhu | 1.0831x | 1.0085x |

Both integer tunes improved every Small BOOM input case by more than 1% in
every placement; neither did so on Medium BOOM. The floating-point controls
changed little on average. Xiangshan's branch result depends strongly on the
input: on Medium BOOM, individual cases range from 0.9599x to 1.1047x after
averaging placements. Random inputs at sizes 128 and 512 improved consistently
across placements, while the mixed pattern at size 128 regressed.

These observations support the hypothesis that a wider out-of-order core can
hide some scheduling differences. They do not establish a universally better
tune or predict SPEC performance. Full case results and raw run artifacts are
in `outputs/boom_cost_model/sensitivity/SUMMARY.md`; the accompanying
`sensitivity.png` and `sensitivity.pdf` show placement ranges, not confidence
intervals.

## Latency and throughput kernels

`run_dataflow.py` adds three unsigned-integer workloads:

| Kernel | Operation | Purpose |
| --- | --- | --- |
| `recurrence` | `state = (state ^ input[i]) * 13 + 7` | Put arithmetic on a dependency chain |
| `independent_streams` | The same recurrence on 1, 2, 4, or 8 independent states | Expose parallel work while consuming the same total number of elements |
| `reduction` | Sum an array into one accumulator | Simple load/add reduction control |

Unsigned 32-bit wraparound is intentional and defined. Inputs come from one
fixed-seed generator. Sizes 32, 128, and 512 are divisible by every supported
stream width; the specialized stream loops require this condition. Each state
starts from a specified seed. A separate scalar reference uses modulo indexing
to check the specialized loops. Every warm-up and every timed result is checked.
Initialization, reference computation, and output are outside timed regions.

The first experiment compares the three existing tunes at `-O3` on Medium BOOM;
it does not force compiler unrolling. Stream width is a workload property,
distinct from a compiler unroll factor. The ISA excludes vector instructions.
The runtime/harness remain fixed at `-O2 -mtune=rocket`, with no LTO. Each of the
18 input cells has three samples of two calls per tune. Three link layouts
rotate variants through matching address slots, giving 486 total samples.
Functions request 2,048-byte alignment so the larger stream variants fit into
balanced slots; recorded addresses are checked before aggregating results.
Each sample warms the function and input before measurement. These working
sets fit in the data cache; memory hierarchy characterization remains separate.

Using the same environment and path variables as above:

```bash
for layout in 0 1 2; do
  python examples/boom_cost_model/run_dataflow.py \
    --gcc "$RISCV_GCC" \
    --runtime-gcc "$CHIPYARD_DIR/.conda-env/riscv-tools/bin/riscv64-unknown-elf-gcc" \
    --simulator "$CHIPYARD_DIR/sims/verilator/simulator-chipyard.harness-MediumBoomV3Config" \
    --dramsim-ini "$CHIPYARD_DIR/generators/testchipip/src/main/resources/dramsim2_ini" \
    --opt O3 --layout "$layout" --timeout 7200 \
    --out "outputs/boom_cost_model/dataflow/medium-layout$layout"
done
python examples/boom_cost_model/summarize_dataflow.py \
  --runs outputs/boom_cost_model/dataflow
```

The driver saves object disassembly alongside cycle results and provenance.
The summary re-parses raw logs, verifies binary hashes and matching experiment
inputs, and rejects unbalanced addresses. It reports tune speedups relative to
Rocket and stream-width speedups relative to the same tune with one stream.
Ratios include common call and counter overhead. Geometric means and placement
ranges describe this experiment; they are not confidence intervals or a SPEC
performance prediction.

### Local dataflow results

All three Medium BOOM layouts passed correctness checks, with 486 validated
cycle samples. At size 512, geometric mean speedups across placements were:

| Workload | generic-ooo vs Rocket | xiangshan-nanhu vs Rocket |
| --- | ---: | ---: |
| Dependent recurrence | 0.7555x | 0.7555x |
| Independent streams, width 1 | 0.7561x | 0.7555x |
| Independent streams, width 2 | 0.8957x | 0.8927x |
| Independent streams, width 4 | 1.3669x | 1.3641x |
| Independent streams, width 8 | 1.6326x | 1.5508x |
| Reduction | 0.9991x | 0.9997x |

The dependent recurrence took 6,224 cycles for Rocket and 8,238 for both
out-of-order tunes in every placement: about 32% more cycles for the latter.
At widths four and eight, both out-of-order tunes won by more than 1% for
every size and placement. Thus the ranking reversal is not confined to the
longest input. The shortest reduction shows some overhead/placement variation;
its unchanged hot-loop instruction sequence does not support a strong tuning
claim from that case.

Rocket expands multiplication by 13 into four shift/add instructions; both
out-of-order tunes use `mulw`. The observations are consistent with a tradeoff
between latency on dependent arithmetic and throughput with independent work.
They do not isolate individual instruction latency or prove that this single
instruction choice explains every measured difference. A useful next cost
model should distinguish dependency chains from available parallelism, then
be tested on held-out kernels.

Full results, raw logs, compact function assembly, exact source snapshots,
and `dataflow.png`/`dataflow.pdf` are saved under
`outputs/boom_cost_model/dataflow/`. This experiment compares existing tunes;
explicit compiler unroll-factor sweeps remain a separate experiment.

## Tests

```bash
python -m unittest discover -s examples/boom_cost_model/tests -v
```

The tests compile all kernels on the host to validate the harness, deliberately
inject an incorrect kernel to check failure detection, and reject malformed
simulation output. Host checks do not produce meaningful cycle measurements.
