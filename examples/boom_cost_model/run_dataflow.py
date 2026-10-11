"""Compare latency, independent integer streams, and reduction on BOOM."""
import statistics

from run_timing import SIZES, TUNES, main

KERNELS = ("recurrence", "independent_streams", "reduction")
WIDTHS = (1, 2, 4, 8)
MARKER = "DATAFLOW_OK sizes=32,128,512 widths=1,2,4,8 repeats=2 samples=3"


def cases():
    """Return valid size/kernel/stream-width cells, without duplicated controls."""
    return [(n, k, w) for n in SIZES for k in range(3)
            for w in (WIDTHS if k == 1 else (1,))]


def parse_dataflow_results(text):
    """Require complete, unique positive samples and successful checks."""
    if MARKER not in text.splitlines():
        raise ValueError("Dataflow harness did not report successful checks")
    expected = {(n, k, w, t) for n, k, w in cases() for t in range(3)}
    measurements = {}
    for line in text.splitlines():
        if not line.startswith("D "):
            continue
        fields = line.split()
        if len(fields) != 8:
            raise ValueError(f"Malformed dataflow measurement: {line}")
        n, k, w, t, *samples = map(int, fields[1:])
        key = (n, k, w, t)
        if key not in expected or key in measurements or min(samples) <= 0:
            raise ValueError(f"Invalid or duplicate dataflow measurement: {line}")
        measurements[key] = samples
    if measurements.keys() != expected:
        raise ValueError("Incomplete dataflow measurements")
    rows = []
    for n, k, w in cases():
        baseline = statistics.median(measurements[n, k, w, 0])
        for t, tune in enumerate(TUNES):
            samples = measurements[n, k, w, t]
            median = statistics.median(samples)
            rows.append({"n": n, "kernel": KERNELS[k], "streams": w, "tune": tune,
                         "cycles": samples, "median_cycles": median,
                         "min_cycles": min(samples), "max_cycles": max(samples),
                         "speedup": baseline / median})
    return rows


if __name__ == "__main__":
    main({"name": "dataflow", "kernels": KERNELS, "harness": "dataflow_timing.c",
          "driver": "run_dataflow.py", "alignment": 2048, "parse": parse_dataflow_results,
          "description": "Warm-cache cycles: 2 calls, 3 samples; sizes 32/128/512, stream widths 1/2/4/8."})
