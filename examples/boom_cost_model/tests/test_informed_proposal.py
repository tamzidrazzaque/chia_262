import json

import pytest

from examples.boom_cost_model.propose_next import parse_choice, compact_evidence
from examples.boom_cost_model.suggest_next import proposal_pool


def test_pool_choice_is_bounded_and_requires_falsifier():
    pool = proposal_pool()
    value = {"candidate_index": 0, "hypothesis": "test throughput", "falsifier": "no kernel change"}
    assert parse_choice(json.dumps(value), pool)["proposal"] == pool[0]
    for change in ({"candidate_index": -1}, {"candidate_index": len(pool)},
                   {"candidate_index": True}, {"falsifier": ""}, {"command": "run anything"}):
        with pytest.raises(ValueError):
            parse_choice(json.dumps({**value, **change}), pool)


def test_prompt_keeps_changed_opcodes_and_omits_full_features():
    baseline = {"speedup": 1.0, "assembly_features": {"multiply": {"opcode_counts": {"slli": 2}}}}
    candidate = {"speedup": 0.9, "assembly_features": {"multiply": {"opcode_counts": {"mul": 1}}}}
    result = compact_evidence({"observations": [baseline, candidate], "surrogate_validation": {"ready": False}})
    assert "assembly_features" not in result["observations"][1]
    assert result["observations"][1]["changed_opcode_counts"] == {"multiply": {"mul": 1, "slli": -2}}
