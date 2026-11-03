"""Bounded, evidence-guided proposals across compiler-cost and policy families."""

from copy import deepcopy

from chia.chipyard.boom_model import GROWTH_PRESETS, validate_policy
from examples.boom_cost_model import campaign_proposals, pressure_proposals
from examples.boom_cost_model.cost_refinement_proposals import AXES, PAIRS

POLICY_AXES = {
    "pressure_algorithm": (0, 1, 2),
    "ira_loop_pressure": (False, True),
    "growth_budget": tuple(GROWTH_PRESETS),
}


class AdaptiveProposals:
    """Enumerated axes vary; every other compiler field remains immutable."""

    def __init__(self, config):
        self.anchor = deepcopy(config["anchor_proposal"])
        self.cost_axes = deepcopy(config.get("cost_axes", {}))
        self.policy_axes = deepcopy(config.get("policy_axes", {}))
        if not isinstance(self.cost_axes, dict) or set(self.cost_axes) - AXES:
            raise ValueError("unsupported adaptive cost axes")
        if not isinstance(self.policy_axes, dict) or set(self.policy_axes) - POLICY_AXES.keys():
            raise ValueError("unsupported adaptive policy axes")
        if not (self.cost_axes or self.policy_axes):
            raise ValueError("adaptive search requires an explicit axis")
        for name, values in self.cost_axes.items():
            bound = 32 if name.startswith("gpr_") else 64
            if not isinstance(values, list) or not 1 <= len(values) <= 12 or any(
                    type(v) is not int or not 1 <= v <= bound for v in values) or len(set(values)) != len(values):
                raise ValueError("invalid bounded cost axis")
        for name, values in self.policy_axes.items():
            if not isinstance(values, list) or not values or any(
                    not any(type(v) is type(a) and v == a for a in POLICY_AXES[name]) for v in values):
                raise ValueError("invalid bounded policy axis")
            if len(set(values)) != len(values):
                raise ValueError("repeated policy choice")
        self.validate(self.anchor)
        self.seeds = deepcopy(config["adaptive_seeds"])
        if not isinstance(self.seeds, list) or not 2 <= len(self.seeds) <= 8:
            raise ValueError("adaptive search requires 2..8 seeds")
        for value in self.seeds:
            self.validate(value)
        keys = [self.identity(p) for p in self.seeds]
        if keys[0] != self.identity(self.anchor) or len(set(keys)) != len(keys):
            raise ValueError("seeds require unique profiles and the exact incumbent first")

    def validate(self, value):
        if not isinstance(value, dict) or value.keys() != {"costs", "move_profile", "policy", "rationale"}:
            raise ValueError("expected complete adaptive compiler profile")
        campaign_proposals.validate({k: value[k] for k in ("costs", "move_profile", "rationale")})
        validate_policy(value["policy"])
        expected = deepcopy(self.anchor)
        expected["rationale"] = value["rationale"]
        for name, choices in self.cost_axes.items():
            family = "move_profile" if name.startswith("gpr_") else "costs"
            number = value[family][name]
            if name in PAIRS:
                if number[0] != number[1]:
                    raise ValueError("integer mode costs must match")
                number = number[0]
            if type(number) is not int or number not in choices:
                raise ValueError("cost outside enumerated choices")
            expected[family][name] = value[family][name]
        for name, choices in self.policy_axes.items():
            v = value['policy'][name]
            if not any(type(v) is type(c) and v == c for c in choices):
                raise ValueError("policy outside enumerated choices")
            expected['policy'][name] = v
        if value != expected:
            changed = [group+'.'+name for group in ('costs','move_profile','policy')
                for name in expected[group] if value[group][name] != expected[group][name]]
            raise ValueError("adaptive profile changes frozen fields: "+', '.join(changed))
        return value

    def project(self, knobs, rationale):
        """Expand only enumerated deltas; the model cannot rewrite frozen fields."""
        if not isinstance(knobs,dict) or set(knobs)-set(self.cost_axes)-set(self.policy_axes):
            unknown = sorted(set(knobs)-set(self.cost_axes)-set(self.policy_axes)) if isinstance(knobs,dict) else ['invalid knobs type']
            raise ValueError('unknown adaptive knob: '+', '.join(unknown)+'; allowed axes: '+', '.join(sorted(set(self.cost_axes)|set(self.policy_axes))))
        value = deepcopy(self.anchor)
        value['rationale'] = rationale
        for name,number in knobs.items():
            group = 'policy' if name in self.policy_axes else 'move_profile' if name.startswith('gpr_') else 'costs'
            value[group][name] = [number,number] if name in PAIRS else number
        return self.validate(value)

    def seed_profiles(self):
        return deepcopy(self.seeds)

    def identity(self, value):
        return pressure_proposals.profile_identity(self.validate(value))

    def feedback_proposal(self, config, history, prior, directory):
        def response(value):
            if isinstance(value,dict) and value.keys()=={'knobs','rationale'}:
                return self.project(value['knobs'],value['rationale'])
            return self.validate(value)  # Read existing complete-schema responses.
        return pressure_proposals.request_json(config, {
            'goal': 'Improve measured SPEC train performance on the fixed MegaBOOM image.',
            'constraints': 'Return JSON {knobs:{axis:value},rationale:string}. Vary ONLY enumerated axes. '
                'Keep all other costs, policy fields, GCC revision, flags, ISA/ABI, libraries and hardware fixed. '
                'Do not repeat measured, reserved or pending profiles. Give a falsifiable code-generation hypothesis. '
                'Costs are heuristics, not measured latencies. Static pressure is not physical register occupancy. '
                'There were no application GPR/FP cross-file moves; no register-parking claims. '
                'Generic kernel rankings did not predict SPEC. No tools, patches, commands, workload changes or RVV. '
                'Reference data is validation only and never enters proposals.',
            'cost_axes': self.cost_axes, 'policy_axes': self.policy_axes, 'immutable_anchor': self.seeds[0],
            'analysis_evidence': config.get('analysis_evidence', {}),
            'history': history, 'prior_train_evidence': prior}, directory, response)
