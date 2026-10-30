import hashlib
import json
from pathlib import Path
import re
import statistics

import pytest

from examples.boom_cost_model.export_research import proposal_data, verified_sample


DATA = Path(__file__).resolve().parents[1] / "research/data"


def test_export_proposal_excludes_unverified_prose_and_worker_paths():
    result = proposal_data({"index": 0, "success": True,
        "proposal": {"costs": {"branch_cost": 3}, "rationale": "PRIVATE_SENTINEL"},
        "compiler": {"compiler_id": "a" * 64, "prefix": "/private/toolchain"}})
    encoded = json.dumps(result)
    assert "PRIVATE_SENTINEL" not in encoded and "/private" not in encoded
    assert result["costs"] == {"branch_cost": 3}


def test_export_requires_simulation_native_correctness_and_finite_time(tmp_path):
    (tmp_path / "correctness.json").write_text('{"success": true, "command": ["PRIVATE_SENTINEL"]}')
    (tmp_path / "completion.json").write_text('{"success": false}')
    assert verified_sample(tmp_path) is None
    (tmp_path / "completion.json").write_text('{"success": true}')
    output = tmp_path / "collected/job/output"
    output.mkdir(parents=True)
    timing = output / "benchmark.csv"
    timing.write_text('name,RealTime\nbenchmark,82.11\n')
    row = verified_sample(tmp_path)
    assert row["guest_seconds"] == 82.11
    assert "PRIVATE_SENTINEL" not in json.dumps(row)
    timing.write_text('name,RealTime\nbenchmark,nan\n')
    with pytest.raises(ValueError, match="invalid collected time"):
        verified_sample(tmp_path)


def test_published_data_hashes_and_privacy():
    manifest = json.loads((DATA / "manifest.json").read_text())
    for name, digest in manifest["files"].items():
        data = (DATA / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest
        value = data.decode()
        assert not re.search(r'/scratch/|/home/|\bi-[0-9a-f]{8,}|\barn:aws:|\b(?:AKIA|ASIA)[A-Z0-9]{16}', value)


def test_paired_export_preserves_controls_repeats_and_worker_identity():
    data = json.loads((DATA / "spec-estimates.json").read_text())
    paired = next(c for c in data["campaigns"] if c["id"] == "paired")
    rows = [r for r in data["samples"] if r["campaign"] == "paired"]
    assert data["estimate"] and not data["SPEC_reportable_score"]
    assert len(rows) == 8 and all(not r["reused"] for r in rows)
    for worker in paired["workers"]:
        samples = [r for r in rows if r["worker"] == worker["worker"]]
        assert len({r["paired_slot"] for r in samples}) == 4
        for kind in ("baseline", "candidate"):
            selected = [r for r in samples if r["role"] == kind]
            assert len(selected) == 2
            assert statistics.median(r["guest_seconds"] for r in selected) == worker["medians"][kind]["648.exchange2_s"]
        assert {r["candidate_index"] for r in samples if r["role"] == "candidate"} == {3}


def test_kernel_duplicate_code_remains_visible():
    data = json.loads((DATA / "fast-kernels.json").read_text())
    history = next(b for b in data["batches"] if b["experiment"] == "history-f2-retry")
    hashes = [r["elf_sha256"] for r in history["variants"].values()]
    assert all(re.fullmatch('[0-9a-f]{64}', value or '') for value in hashes)
    assert len(set(hashes)) < len(hashes)
    assert all(r["elapsed_ns"] > 0 for r in data["samples"])
