"""Check the independent oracle against executable kernels and reject bad runs."""

import json
from pathlib import Path
import subprocess

import pytest

from chia.chipyard.fast_screen import expected_checksums, validate_records
from examples.boom_cost_model.fast_campaign import validate_outputs, executable_aliases, select_worker


def records():
    return [{"kernel": k, "repeat": rep, "checksum": v, "elapsed_ns": 10}
            for k, v in expected_checksums().items() for rep in range(3)]


def encode(rows):
    return "\n".join(json.dumps(r) for r in rows).encode()


def test_python_oracle_matches_native_kernels(tmp_path):
    source = Path(__file__).parents[3] / "examples/boom_cost_model/fast_kernels.c"
    exe = tmp_path / "kernels"
    subprocess.run(["cc", "-O2", str(source), "-o", str(exe)], check=True)
    data = subprocess.check_output([str(exe)])
    assert validate_records(data)["success"]


@pytest.mark.parametrize("bad", ["checksum", "time", "missing", "duplicate"])
def test_bad_measurements_cannot_be_scored(bad):
    rows = records()
    if bad == "checksum": rows[0]["checksum"] += 1
    if bad == "time": rows[0]["elapsed_ns"] = 0
    if bad == "missing": rows.pop()
    if bad == "duplicate": rows[-1] = rows[0]
    with pytest.raises(ValueError):
        validate_records(encode(rows), hardware=True)


def test_collection_and_variant_exit_codes_are_required():
    output = {"output/job.status": b"0", "output/baseline.status": b"0",
              "output/baseline.jsonl": encode(records())}
    assert validate_outputs(output, True, ["baseline"])["baseline"]["success"]
    output["output/baseline.status"] = b"1"
    with pytest.raises(ValueError):
        validate_outputs(output, True, ["baseline"])
    output["output/baseline.status"] = b"0"
    with pytest.raises(ValueError):
        validate_outputs(output, False, ["baseline"])


def test_identical_executables_share_one_measured_output_with_explicit_lineage():
    files = {"root/fast/baseline": b"same", "root/fast/candidate": b"same", "root/fast/other": b"different"}
    aliases = executable_aliases(files, ["baseline", "candidate", "other"])
    assert aliases == {"baseline": "baseline", "candidate": "baseline", "other": "other"}
    outputs = {"output/job.status": b"0", "output/baseline.status": b"0", "output/baseline.jsonl": encode(records())}
    result = validate_outputs(outputs, True, ["baseline", "candidate"], hardware=True, aliases=aliases)
    assert result["baseline"]["independent_variant"]
    assert not result["candidate"]["independent_variant"]
    assert result["candidate"]["canonical_executable"] == "baseline"


def test_worker_selection_cannot_add_an_unapproved_host():
    config = {"security_policy": "fixed", "fpga_workers": [
        {"instance_id": "a", "ssh_alias": "first"}, {"instance_id": "b", "ssh_alias": "second"}]}
    selected = select_worker(config, "second")
    assert selected["fpga_workers"] == [config["fpga_workers"][1]]
    assert selected["security_policy"] == "fixed" and len(config["fpga_workers"]) == 2
    with pytest.raises(ValueError):
        select_worker(config, "outside-host")
