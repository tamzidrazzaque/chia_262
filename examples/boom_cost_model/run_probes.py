"""Measure fixed instruction chains and independent streams, not GCC choices."""
from run_timing import main
from run_workloads import parse_measurements

KERNELS = ("probe_mul", "probe_shift", "probe_add", "probe_load")
CASES = [(k, n, width) for k in range(4) for n in (128, 512) for width in (1, 8)]
MARKER = "PROBES_OK cases=16 repeats=2 samples=3 block=32"


def parse_probe_results(text):
    """Require complete, checked instruction-probe measurements."""
    return parse_measurements(text, "P", MARKER, CASES, KERNELS)


if __name__ == "__main__":
    main({"name": "probes", "kernels": KERNELS, "harness": "probe_timing.c",
          "driver": "run_probes.py", "extra_sources": ["run_workloads.py", "kernels/probe_body.h"],
          "alignment": 2048, "parse": parse_probe_results,
          "description": "Fixed assembly: 2 calls, 3 samples; 128/512 operations, 1/8 independent chains."})
