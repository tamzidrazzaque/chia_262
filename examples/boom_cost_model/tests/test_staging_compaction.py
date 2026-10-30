import subprocess

import pytest

from examples.boom_cost_model import tasks


def test_compacts_only_completed_spec_image_without_changing_bytes(tmp_path, monkeypatch):
    name = "spec17-intspeed-train-a032f1bf-602.gcc_s"
    image_name = f"{name}0-{name}.img"
    payload = b"header" + b"\0" * (1024 * 1024) + b"footer"
    (tmp_path / "rsyncdir").mkdir()
    images = [tmp_path / image_name, tmp_path / "rsyncdir" / image_name]
    for image in images:
        image.write_bytes(payload)

    original_run = subprocess.run

    def no_active_driver(args, *positional, **keywords):
        if args[:2] == ["pgrep", "-af"]:
            return subprocess.CompletedProcess(args, 1, "", "")
        return original_run(args, *positional, **keywords)

    monkeypatch.setattr(tasks.subprocess, "run", no_active_driver)
    assert tasks.compact_completed_spec_image(name, tmp_path) >= 0
    assert all(image.read_bytes() == payload for image in images)


def test_rejects_unrelated_image_name(tmp_path):
    with pytest.raises(ValueError, match="unexpected SPEC workload"):
        tasks.compact_completed_spec_image("another-user-job", tmp_path)
