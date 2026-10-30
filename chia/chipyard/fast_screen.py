"""Correctness and timing summaries for independent compiler screening kernels."""

import json
import math
import statistics

KERNELS = ("stream", "branch", "pointer", "multiply", "divide", "floating")


def expected_checksums():
    """Independent Python oracle; unsigned wraparound matches the C kernels."""
    mask, n, rounds = (1 << 64) - 1, 4096, 32
    data, seed = [], 123
    for _ in range(n):
        seed = (seed * 6364136223846793005 + 1) & mask
        data.append(seed >> 32)
    stream = (sum(data) * 7 * rounds + n * sum(range(rounds))) & mask
    branch = 1
    for r in range(rounds):
        for d in data:
            branch = (branch + (d ^ r) if d & 256 else branch ^ (d + r)) & mask
    pointer, p = 0, 0
    for _ in range(n * rounds):
        p = (p * 5 + 1) & (n - 1)
        pointer = (pointer + data[p]) & mask
    values = [17, 19, 23, 29]
    for i in range(n * rounds):
        values = [(v * m + i) & mask for v, m in zip(values, (7, 11, 13, 17))]
    multiply = values[0] ^ values[1] ^ values[2] ^ values[3]
    divide = sum((d + r * 65537) // ((data[(i + 1) & (n - 1)] & 31) + 1)
                 for r in range(rounds) for i, d in enumerate(data)) & mask
    floating = sum(d & 1023 for d in data) * rounds * 15
    return dict(zip(KERNELS, (stream, branch, pointer, multiply, divide, floating)))


def validate_records(data: bytes, hardware=False):
    records = [json.loads(line) for line in data.splitlines()]
    expected = expected_checksums()
    if len(records) != len(KERNELS) * 3 or {(r["kernel"], r["repeat"]) for r in records} != {
            (k, rep) for k in KERNELS for rep in range(3)}:
        raise ValueError("missing or duplicate kernel/repeat")
    for r in records:
        if r["checksum"] != expected[r["kernel"]] or type(r["elapsed_ns"]) is not int or r["elapsed_ns"] <= 0:
            raise ValueError("kernel checksum or timer failed")
    return {"success": True, "FPGA_executed": hardware, "records": records,
            "median_ns": {k: statistics.median(r["elapsed_ns"] for r in records if r["kernel"] == k)
                          for k in KERNELS}}


def geometric_speedup(baseline, candidate):
    if baseline.keys() != candidate.keys() or not baseline or any(
            not math.isfinite(v) or v <= 0 for v in [*baseline.values(), *candidate.values()]):
        raise ValueError("invalid or unpaired measurements")
    return math.exp(statistics.mean(math.log(baseline[k] / candidate[k]) for k in baseline))
