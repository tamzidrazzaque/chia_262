"""Application overlay and guest shutdown/error propagation checks."""

import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from examples.rocket_cost_model.prepare_zstd_image import overlay


def pilot(tmp_path):
    data = tmp_path / "corpora"
    data.mkdir()
    (data / "train.tar").write_bytes(b"input")
    binary = tmp_path / "zstd"
    binary.write_bytes(b"application")
    sha = lambda value: hashlib.sha256(value).hexdigest()
    (tmp_path / "manifest.json").write_text(json.dumps({"source_revision": "pin",
        "builds": {"rocket": {"binary": str(binary), "sha256": sha(b"application"), "flags": []}},
        "corpora": {"train": {"sha256": sha(b"input")}}}))
    return tmp_path


def test_overlay_binds_input_executable_and_runner(tmp_path):
    prepared = overlay(pilot(tmp_path))
    assert prepared["files"]["root/zstd-pilot/zstd"] == b"application"
    assert prepared["identity"]["input_set"] == "train"
    assert prepared["modes"]["root/zstd-pilot/zstd"] == 0o755
    (tmp_path / "zstd").write_bytes(b"changed")
    with pytest.raises(ValueError, match="bytes changed"):
        overlay(tmp_path)


def test_failure_still_reaches_collection_and_parent_shutdown(tmp_path):
    prepared = overlay(pilot(tmp_path))
    command = prepared["config"]["jobs"][0]["command"]
    command = command.replace("mkdir -p /output", "true")
    command = command.replace("cp /root/zstd-pilot/identity.json /output/identity.json", "true")
    command = command.replace("bash /root/zstd-pilot/run.sh /root/zstd-pilot/zstd /root/zstd-pilot/input.tar /output", "false")
    status = tmp_path / "collection.status"
    command = command.replace("/output/collection.status", str(status))
    result = subprocess.run(["sh", "-c", command + "; echo shutdown-reached"], capture_output=True, text=True)
    assert result.returncode == 0 and "shutdown-reached" in result.stdout
    assert status.read_text().strip() == "1"
