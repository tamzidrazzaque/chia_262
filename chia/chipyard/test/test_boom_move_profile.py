import pytest

from chia.chipyard.boom_model import render_move_profile, validate_move_profile
from examples.boom_cost_model.campaign_proposals import seed_profiles, validate, identity


def test_directional_hooks_preserve_secondary_cost_and_legacy_fallback():
    text = ('  if ((from == FP_REGS && to == GR_REGS) ||\n'
            '      (from == GR_REGS && to == FP_REGS))\n    return tune_param->fmv_cost;\n'
            '  return (tune_param->memory_cost\n\t  + memory_move_secondary_cost (mode, rclass, in));')
    p = seed_profiles()[2]["move_profile"]
    result = render_move_profile(text, p)
    assert result.count("if (tune_param == &boom_tune_info)") == 2
    assert "from == GR_REGS && to == FP_REGS) return 6" in result
    assert "from == FP_REGS && to == GR_REGS) return 12" in result
    assert "cost = in ? 8 : 5" in result
    assert "return cost + memory_move_secondary_cost (mode, rclass, in)" in result
    assert "return tune_param->fmv_cost" in result
    assert "return (tune_param->memory_cost" in result


@pytest.mark.parametrize("change", [{"gpr_load": True}, {"fpr_store": 0}, {"gpr_to_fpr": 33}, {"command": "anything"}])
def test_profile_rejects_unbounded_values_and_commands(change):
    with pytest.raises(ValueError):
        validate_move_profile({**seed_profiles()[0]["move_profile"], **change})


def test_profiles_are_coordinated_distinct_and_data_only():
    profiles = seed_profiles()
    assert len({identity(p) for p in profiles}) == 4
    for p in profiles:
        assert validate(p) == p
        with pytest.raises(ValueError):
            validate({**p, "patch": "arbitrary source"})
