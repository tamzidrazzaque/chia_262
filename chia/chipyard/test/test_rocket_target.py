"""Offline target/driver rejection gates; no target performance is simulated."""

import hashlib

import pytest

from chia.chipyard import rocket_target as target


def manifest(tmp_path):
    result = dict(AGFI=target.AGFI, AFI=target.AFI, quintuplet=target.QUINTUPLET,
                  shell="0x10212415", Chipyard_revision=target.CHIPYARD,
                  FireSim_revision=target.FIRESIM, Rocket_revision=target.ROCKET,
                  matching_source_verified=True)
    for field in ("driver_bundle", "build_evidence"):
        path = tmp_path / field
        path.write_bytes(b"test fixture, not a real driver")
        result[field] = str(path)
        result[field + "_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def test_requires_pinned_provenance(tmp_path):
    hw = manifest(tmp_path)
    target.validate_hardware(hw)
    hw["matching_source_verified"] = False
    with pytest.raises(ValueError, match="not verified"):
        target.validate_hardware(hw)


@pytest.mark.parametrize("field", ["AGFI", "AFI", "quintuplet", "shell",
                                  "Chipyard_revision", "FireSim_revision", "Rocket_revision"])
def test_rejects_another_target(tmp_path, field):
    hw = manifest(tmp_path)
    hw[field] = "another target"
    with pytest.raises(ValueError, match="mismatch"):
        target.validate_hardware(hw)


@pytest.mark.parametrize("field", ["driver_bundle", "build_evidence"])
def test_rejects_changed_artifacts(tmp_path, field):
    hw = manifest(tmp_path)
    from pathlib import Path
    Path(hw[field]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash differs"):
        target.validate_hardware(hw)


def test_rejects_stale_aws_state(tmp_path):
    hw = manifest(tmp_path)
    image = dict(FpgaImageGlobalId=target.AGFI, FpgaImageId=target.AFI,
                 ShellVersion=hw["shell"], State={"Code": "available"},
                 Description=f"firesim-deployquintuplet:{target.QUINTUPLET},firesim-commit:{target.FIRESIM}")
    target.validate_image(hw, image)
    image["State"]["Code"] = "failed"
    with pytest.raises(ValueError):
        target.validate_image(hw, image)


def test_rocket_adapter_keeps_megaboom_guard():
    from examples.rocket_cost_model.experiment import RocketExperiment
    from examples.boom_cost_model.optimize import Experiment
    with pytest.raises(ValueError, match="MegaBOOM"):
        Experiment.validate_hardware(None, {"matching_source_verified": True,
            "quintuplet": target.QUINTUPLET})
    assert RocketExperiment.workload_flags(None) == target.SCALAR_FLAGS
