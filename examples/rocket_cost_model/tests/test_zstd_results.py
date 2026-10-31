"""Reject incomplete/mismatched application evidence; no performance fixtures."""

import hashlib

import pytest

from examples.rocket_cost_model.zstd_results import measurement_key, validate


def evidence():
    binary, data, compressed = b"binary", b"real input fixture", b"compressed fixture"
    sha = lambda b: hashlib.sha256(b).hexdigest()
    outputs = {"output/job.status": b"0\n", "output/collection.status": b"0\n",
               "output/correctness.txt": b"correct\n", "output/decoded.tar": data,
               "output/compressed.zst": compressed, "output/compress.time": b"real 1.25\n",
               "output/decompress.time": b"real 0.25\n",
               "output/inputs.sha256": f"{sha(binary)}  /zstd\n{sha(data)}  /input.tar\n".encode(),
               "output/outputs.sha256": f"{sha(compressed)}  compressed.zst\n{sha(data)}  decoded.tar\n".encode()}
    return outputs, sha(data), sha(binary)


def test_functional_evidence_is_never_labeled_fpga():
    outputs, data, binary = evidence()
    assert validate(outputs, data, binary, True, "qemu")["FPGA_executed"] is False
    assert validate(outputs, data, binary, True, "native")["FPGA_executed"] is False


@pytest.mark.parametrize("field,value", [("job.status", b"1"), ("collection.status", b"1"),
    ("correctness.txt", b""), ("decoded.tar", b"wrong bytes"), ("compressed.zst", b"changed"),
    ("compress.time", b"real 0"), ("decompress.time", b"real nan"),
    ("inputs.sha256", b""), ("outputs.sha256", b"")])
def test_bad_evidence_rejected(field, value):
    outputs, data, binary = evidence()
    outputs["output/" + field] = value
    with pytest.raises(ValueError):
        validate(outputs, data, binary, True, "fpga")


def test_missing_completion_and_ambiguous_paths_rejected():
    outputs, data, binary = evidence()
    with pytest.raises(ValueError):
        validate(outputs, data, binary, False, "fpga")
    outputs["other/job.status"] = b"0"
    with pytest.raises(ValueError, match="ambiguous"):
        validate(outputs, data, binary, True, "fpga")


def test_repeats_workers_and_campaign_phases_are_distinct():
    software = {name: "a" * 64 for name in ("binary_sha256", "input_sha256", "runner_sha256",
                "rootfs_sha256", "bootbinary_sha256", "runtime_sha256")}
    hardware = {"AGFI": "rocket", "quintuplet": "rocket-target", "driver_bundle_sha256": "b" * 64}
    keys = {measurement_key(software, hardware, worker, phase, sample)
            for worker in ("a", "b") for phase in ("search", "confirmation") for sample in (0, 1)}
    assert len(keys) == 8
    with pytest.raises(ValueError):
        measurement_key({}, {}, "a", "search", True)


def test_cache_key_requires_full_runtime_identity():
    with pytest.raises(ValueError, match="incomplete software"):
        measurement_key({"binary_sha256": "a" * 64}, {"AGFI": "rocket"}, "a", "search", 0)
