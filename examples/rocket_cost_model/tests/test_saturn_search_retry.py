"""A failed measurement must not suppress a later identical-ELF retry."""

import argparse
import json
from unittest.mock import patch

from examples.rocket_cost_model import saturn_search_loop as loop


def test_failed_measurement_can_be_retried(tmp_path):
    baseline = dict(platform_sha256="p", agfi="a", driver_sha256="d",
                    vlen_bits=256, input_id="mcf", cycles=100)
    queue = tmp_path / "queue"
    queue.mkdir()
    (queue / "3.24.json").write_text(json.dumps({"candidate_id": "3.24"}))
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(baseline))
    state = tmp_path / "state.json"
    elf = "a" * 64
    state.write_text(json.dumps({"baseline": baseline, "candidates": [
        {"candidate_id": "3.10", "status": "rejected", "executable_sha256": elf}]}))
    calls = []

    def hook(command, env, label):
        calls.append(label)
        work = loop.Path(env["SATURN_WORKDIR"])
        if label == "prepare":
            (work / "candidate-metadata.json").write_text(json.dumps({"executable_sha256": elf, "bundle_sha256": "b" * 64}))
        else:
            (work / "candidate-receipt.json").write_text(json.dumps({
                "status": "correct", "identity": {**baseline, "role": "3-saturn-aware", "bundle_sha256": "b" * 64},
                "whole_boot_simulation_cycles": 90,
                "executable_sha256": elf,
                "collected_sha256": {"result/executable.sha256": elf}}))

    args = argparse.Namespace(queue=queue, baseline=baseline_path, state=state,
        work_root=tmp_path / "work", prepare_cmd="prepare", measure_cmd="measure",
        once=True, watch=False)
    with patch.object(loop, "_run_hook", hook):
        loop.run(args)
    assert calls == ["prepare", "measure"]
    assert json.loads(state.read_text())["candidates"][-1]["cycles"] == 90
