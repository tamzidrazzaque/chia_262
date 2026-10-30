import pytest

from chia.chipyard.cost_model import BASE_COSTS
from chia.chipyard.tuning_search import features, suggest, validation_report


def proposal(memory):
    return {"costs": {**BASE_COSTS, "memory_cost": memory}, "tuning": "boom"}


def observed(memory, **changes):
    return {"proposal": proposal(memory), "speedup": 1 + memory / 100,
            "correct": True, "FPGA_executed": True, "target_id": "fixed",
            "executable_sha256": f"{memory:064x}", **changes}


def test_cold_start_explores_and_never_repeats():
    chosen = suggest([proposal(1), proposal(5), proposal(20)], [observed(5)])
    assert chosen["strategy"] == "diversity exploration"
    assert features(chosen["proposal"]) != features(proposal(5))
    assert not chosen["validation"]["ready"]


def test_leave_configuration_out_validation_is_measured():
    report = validation_report([observed(i) for i in range(1, 10)])
    assert report["ready"]
    assert report["leave_one_executable_group_out_pair_accuracy"] > 0.6


def test_identical_generated_code_is_not_independent_training_data():
    data = [observed(i, executable_sha256="a" * 64) for i in range(1, 10)]
    report = validation_report(data)
    assert not report["ready"]
    assert report["unique_configurations"] == 9 and report["unique_executables"] == 1


@pytest.mark.parametrize("change", [{"FPGA_executed": False}, {"correct": False}, {"speedup": float('nan')}])
def test_invalid_and_qemu_labels_rejected(change):
    with pytest.raises(ValueError):
        validation_report([observed(1, **change)])


def test_mixed_targets_and_repeat_leakage_rejected():
    with pytest.raises(ValueError):
        validation_report([observed(1), observed(2, target_id="other")])
    with pytest.raises(ValueError):
        validation_report([observed(1), observed(1)])
