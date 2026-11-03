"""Separate the winning pressure mechanisms and refine its loop-growth budget."""

from copy import deepcopy

from chia.chipyard.boom_model import GROWTH_PRESETS
from examples.boom_cost_model import pressure_proposals as pressure

GROWTH_CHOICES = ('default', 'compact', 'tight', 'relaxed', 'peel_only', 'jam_only')

def validate(value):
    return pressure.validate_profile(value, GROWTH_CHOICES)


def identity(value):
    return pressure.profile_identity(validate(value))


def seed_profiles():
    definitions = [
        (2, True, "compact", "Confirmed pressure-round winner control; retain the identical compiler and scalar costs."),
        (2, False, "compact", "Scheduling-only ablation: disable the IRA pressure default while keeping model scheduling and compact growth."),
        (0, True, "compact", "IRA-only ablation: retain IRA loop pressure and compact growth while returning scheduling pressure to its original default."),
        (2, True, "tight", "Reduce complete-peel budget from 64 to 32, with unroll/jam factor1 fixed; test code-growth versus branch/ILP tradeoffs."),
        (2, True, "relaxed", "Increase complete-peel budget from 64 to 128, with unroll/jam factor1 fixed; test whether the winner suppressed useful expansion."),
        (2, True, "peel_only", "Keep peel budget64 but restore unroll/jam factor4; separate the two components of compact growth."),
    ]
    return [validate({"costs": deepcopy(pressure.ANCHOR_COSTS), "move_profile": dict(pressure.ANCHOR_MOVES),
        "policy": {"pressure_algorithm": algorithm, "ira_loop_pressure": ira, "growth_budget": growth},
        "rationale": rationale}) for algorithm, ira, growth, rationale in definitions]


def feedback_proposal(config, history, prior, directory):
    return pressure.feedback_proposal(config, history, prior, directory, example=seed_profiles()[0],
        validator=validate, growth_choices=GROWTH_CHOICES)
