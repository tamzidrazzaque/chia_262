# Cache-sensitive workload selection

Tune for measured runtime on the fixed hardware, including instruction
footprint and data locality. Execution-unit utilization is only one possible
mechanism. Neither static instruction counts nor working-set size alone
establish a cache bottleneck.

The matching MegaBOOM V3 source selects 64 sets and eight ways for each L1;
the pinned Rocket parameters use 64-byte lines. Each L1 therefore holds
32 KiB. The current public image has a 4 MiB last-level cache. These are source
capacities, not measurements of occupancy or cache-miss rates. The adjacent
`MegaBoomChiaBigCacheConfig` is a different configuration and must not be used
to describe this image.

## First establish cache sensitivity

`cache_probe.c` is original, redistributable code. It traverses working sets
of 8, 16, 32, 64, 256, 1024, 4096 and 16384 KiB, with one 64-byte node per line.
It compares a shuffled single-cycle dependent pointer chain and sequential
streaming. Every page is touched before timing; each kernel call makes two
complete traversals. Calibration doubles the calls per timed batch until it
takes at least 1 ms, bounded at 33,554,432 loads. Three measured samples use
that batch size. Compare elapsed time **per load**, using the recorded counts.
Fixed volatile loads intentionally
keep this a hardware diagnostic. Independent arithmetic checksums, complete
case coverage, guest exit and collection gates are required. QEMU validates
functionality; its timings are not hardware performance evidence.

Prepare using the existing authenticated, loopback-only cluster environment:

```bash
python -m examples.boom_cost_model.prepare_probes --suite cache \
  --config /path/to/private-config.json --run-dir /path/to/cache-prepared
```

An optional supervisor settings entry runs that prepared suite once between
drained campaigns, then resumes normal experiments automatically:

```json
{"cache_probe": {
  "config": "/path/to/private-config.json",
  "prepared_directory": "/path/to/cache-prepared",
  "result_directory": "/path/to/cache-results",
  "failure_policy": "quarantine"
}}
```

It waits for QEMU correctness without holding ordinary experiments, verifies
both workers are idle before dispatch, and uses the existing full image,
driver, AWS, SSH and output-validation gates. It never interrupts live FPGA
work. With `failure_policy: quarantine`, a failed optional diagnostic is
preserved and rejected, then ordinary experiments may continue after their
idle/cloud/hardware checks. It is not retried automatically or accepted as a
score. Without that explicit policy, diagnostic failure stops the supervisor.

The first FPGA version failed on both workers at the resident 8 KiB stream:
256 loads took zero reported nanoseconds. Checksums were correct and simulation
passed, but the guest exited nonzero as required by the timing gate. QEMU had
not reproduced that clock granularity. Recipe v2 uses calibrated batching and
has a regression test that quantizes the clock to 4 microseconds. The old
failure remains evidence; no cache-performance claim is based on it.

Compare time per load across capacities, separately for each worker and access
pattern. Cache and TLB/page effects can coexist. A latency knee is supporting
evidence, not a direct cache-miss counter. Stream throughput can reflect memory
bandwidth and outstanding-load capacity; pointer chasing deliberately limits
memory-level parallelism. Do not collapse these into one proxy score or claim
compiler improvement from this diagnostic.

## Then choose a compiler-sensitive application

For data locality, screen an original multidimensional stencil/transpose with
a verified working set above the LLC, plus a small resident control. Compare
loop interchange/blocking decisions and emitted code before expensive trials.
An explicitly hand-blocked version can validate that the workload is sensitive
to locality, but its speedup is a source transformation, not a learned compiler
cost-model result. Keep source identical when comparing compiler candidates.
Use MCF as a possible irregular-memory generalization check only after measuring
its behavior here; pointer dependencies may leave little room for these compiler
heuristics. MCF's long existing runs make it unsuitable as the initial fast
feedback workload. Do not assume Exchange2 strains the data cache.

For instruction locality, test a separate footprint family on Leela/GCC only
after showing an application/hot-code footprint and useful layout or inlining
change. Sweep inlining, unrolling, peeling and layout in controlled ablations.
Leela's previous compact versus unroll timing difference does not prove an
instruction-cache cause. Lower code size alone is not the objective.

Simply setting `l1-cache-size`, `l1-cache-line-size` or `l2-cache-size` is not a
general cache simulator. In our pinned GCC, their numerical uses are in the
software-prefetch pass (and the line-size C++ interference default). The
RISC-V prefetch instruction requires Zicbop, which the fixed rv64imafdc baseline
does not enable. Do not add an unsupported ISA extension, change ABI-sensitive
C++ interference defaults, or spend FPGA time on unchanged executables.

Sources: [pinned BOOM configuration](https://github.com/riscv-boom/riscv-boom/blob/5223e44cfeb26f41380057a2eb4d651197475f69/src/main/scala/v3/common/config-mixins.scala),
[pinned Rocket cache parameters](https://github.com/chipsalliance/rocket-chip/blob/55bcad0f59436de98ea510334121de8546b9e9d7/src/main/scala/rocket/ICache.scala),
[GCC 13.2 optimization options](https://gcc.gnu.org/onlinedocs/gcc-13.2.0/gcc/Optimize-Options.html),
[pinned GCC prefetch guard](https://github.com/gcc-mirror/gcc/blob/c891d8dc23e1a46ad9f3e757d09e57b500d40044/gcc/config/riscv/riscv.md).
