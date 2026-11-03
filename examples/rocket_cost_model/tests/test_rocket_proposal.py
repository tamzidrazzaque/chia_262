"""Keep the initial Rocket proposal space limited to scalar cost tables."""

from copy import deepcopy

import pytest

from chia.chipyard.cost_model import BASE_COSTS
from examples.rocket_cost_model.build_candidate import validate_proposal


def proposal():
    return {"costs": deepcopy(BASE_COSTS), "hypothesis": "Describe expected changed code", "falsifier": "Describe disconfirming evidence"}


def test_complete_cost_proposal_accepted():
    assert validate_proposal(proposal())["costs"] == BASE_COSTS


@pytest.mark.parametrize("change", ["extra_flags", "scheduling", "missing_cost", "empty_falsifier", "unbounded_cost"])
def test_changes_outside_initial_search_rejected(change):
    value = proposal()
    if change == "extra_flags": value["flags"] = "-march=rv64gcv"
    elif change == "scheduling": value["scheduling"] = {"issue_rate": 8}
    elif change == "missing_cost": value["costs"].pop("memory_cost")
    elif change == "empty_falsifier": value["falsifier"] = ""
    else: value["costs"]["branch_cost"] = 1000
    with pytest.raises(ValueError):
        validate_proposal(value)
