"""Compare FIR, matrix multiplication, and cache-line pointer chains on BOOM."""
import statistics

from run_timing import TUNES, main

KERNELS = ("fir", "matmul", "pointer_chase")
# (kernel index, n, parameter): FIR outputs/taps, matrix dimension/unused,
# pointer backing words/chains. Same input and work across all tunes.
CASES = ([(0, n, taps) for n in (32, 128, 512) for taps in (8, 32)]
         + [(1, n, 0) for n in (4, 8, 16)]
         + [(2, n, chains) for n in (64, 4096, 16384) for chains in (1, 4)])
MARKER = "WORKLOADS_OK cases=15 repeats=2 samples=3"


def parse_measurements(text, prefix, marker, cases, kernels):
    """Validate exact case coverage and summarize three positive cycle samples."""
    if marker not in text.splitlines():
        raise ValueError("Harness did not report successful correctness checks")
    expected = {(k, n, p, t) for k, n, p in cases for t in range(3)}
    measurements = {}
    for line in text.splitlines():
        if not line.startswith(prefix + " "):
            continue
        fields = line.split()
        if len(fields) != 8:
            raise ValueError(f"Malformed measurement: {line}")
        k, n, p, t, *samples = map(int, fields[1:])
        key = (k, n, p, t)
        if key not in expected or key in measurements or min(samples) <= 0:
            raise ValueError(f"Invalid or duplicate measurement: {line}")
        measurements[key] = samples
    if measurements.keys() != expected:
        raise ValueError("Incomplete measurements")
    rows = []
    for k, n, p in cases:
        baseline = statistics.median(measurements[k, n, p, 0])
        for t, tune in enumerate(TUNES):
            samples = measurements[k, n, p, t]
            median = statistics.median(samples)
            rows.append({"kernel": kernels[k], "n": n, "streams": p,
                         "tune": tune, "cycles": samples, "median_cycles": median,
                         "min_cycles": min(samples), "max_cycles": max(samples),
                         "speedup": baseline / median})
    return rows


def parse_workload_results(text):
    """Require all 15 workload cases and correctness checks."""
    return parse_measurements(text, "W", MARKER, CASES, KERNELS)


if __name__ == "__main__":
    main({"name": "workloads", "kernels": KERNELS, "harness": "workload_timing.c",
          "driver": "run_workloads.py", "alignment": 2048, "parse": parse_workload_results,
          "max_cycles": 30000000,
          "description": "2 calls, 3 samples; FIR outputs/taps, matrix dimension, pointer words/chains. Parameter is printed as streams."})
