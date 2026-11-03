"""Configurable cost-weight search under a fixed, verified compiler policy."""

from copy import deepcopy

from chia.chipyard.boom_model import validate_policy
from examples.boom_cost_model import campaign_proposals, pressure_proposals


AXES = {"branch_cost", "memory_cost", "int_mul", "int_div", "gpr_load", "gpr_store"}
PAIRS = {"int_mul", "int_div"}


class CostRefinementProposals:
    """Bound every variable cost; freeze all other costs and optimization policy."""

    def __init__(self, config):
        self.anchor = deepcopy(config["anchor_proposal"])
        self.axes = deepcopy(config["cost_axes"])
        if not isinstance(self.axes, dict) or not self.axes or set(self.axes) - AXES:
            raise ValueError("unsupported cost-search axes")
        for name, values in self.axes.items():
            bound = 32 if name.startswith("gpr_") else 64
            if not isinstance(values, list) or not 1 <= len(values) <= 12 or any(
                    type(value) is not int or not 1 <= value <= bound for value in values):
                raise ValueError("cost axes require bounded integer choices")
            if len(set(values)) != len(values):
                raise ValueError("cost axis repeats a choice")
        self.validate(self.anchor)
        definitions = config["cost_seeds"]
        if not isinstance(definitions, list) or not 2 <= len(definitions) <= 10:
            raise ValueError("cost search requires 2..10 seed definitions")
        if definitions[0].get("knobs") != {}:
            raise ValueError("first cost seed must be the unchanged incumbent")
        self.seeds = [self.validate(self.project(row["knobs"], row["rationale"])) for row in definitions]
        if len({self.identity(p) for p in self.seeds}) != len(self.seeds):
            raise ValueError("cost seeds repeat a profile")

    def project(self, knobs, rationale):
        """Apply only enumerated axes to a fresh copy of the incumbent."""
        if not isinstance(knobs, dict) or set(knobs) - set(self.axes):
            raise ValueError("unknown cost knob")
        value = deepcopy(self.anchor)
        value["rationale"] = rationale
        for name, number in knobs.items():
            if type(number) is not int or number not in self.axes[name]:
                raise ValueError("cost knob outside enumerated choices")
            family = "move_profile" if name.startswith("gpr_") else "costs"
            value[family][name] = [number, number] if name in PAIRS else number
        return value

    def validate(self, value):
        if not isinstance(value, dict) or value.keys() != {"costs", "move_profile", "policy", "rationale"}:
            raise ValueError("expected complete cost profile and fixed policy")
        campaign_proposals.validate({k: value[k] for k in ("costs", "move_profile", "rationale")})
        validate_policy(value["policy"])
        knobs = {}
        for name in self.axes:
            family = "move_profile" if name.startswith("gpr_") else "costs"
            number = value[family][name]
            if name in PAIRS:
                if number[0] != number[1]:
                    raise ValueError("integer cost choices must apply equally to both modes")
                number = number[0]
            knobs[name] = number
        if value != self.project(knobs, value["rationale"]):
            raise ValueError("cost proposal changes frozen fields or policy")
        return value

    def seed_profiles(self):
        return deepcopy(self.seeds)

    def identity(self, value):
        return pressure_proposals.profile_identity(self.validate(value))

    def feedback_proposal(self, config, history, prior, directory):
        prompt = {"goal": "Improve Exchange2 train performance beyond the confirmed BOOM incumbent by retuning cost weights under its fixed policy.",
            "constraints": "Return exactly the example's complete JSON schema. Change only the enumerated cost axes. "
                "int_mul/int_div choices apply equally to both 32/64-bit cost entries. Keep optimization policy, other costs, "
                "ISA/ABI, compiler revision, command-line flags, libraries and hardware fixed. Never repeat a measured or pending "
                "profile. Explain expected generated-code change and falsification. These are compiler heuristics, not measured "
                "hardware latencies. Do not infer cycle bottlenecks from static pressure or functional call counts. "
                "Application cross-file moves were absent; do not invent register-parking explanations. Generic microkernel "
                "ranking failed validation. Previous observations under another policy are context, not scores here. "
                "Reference inputs are held out. No patches, tools, commands, new flags or workload changes.",
            "allowed_axes": self.axes, "example": self.seed_profiles()[0],
            "analysis_evidence": config.get("analysis_evidence", {}), "history": history,
            "prior_train_evidence": prior, "incremental_promotion_margin": config.get("min_incremental_improvement")}
        return pressure_proposals.request_json(config, prompt, directory, self.validate)
