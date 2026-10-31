"""Rocket-specific target checks over the handoff's SPEC build/measurement stages.

This provides reusable stages, not an autonomous campaign entry point. A caller
must supply a verified hardware manifest and approved existing worker config.
"""

from ray import cloudpickle
import sys

from chia.chipyard import rocket_target
from examples.boom_cost_model.optimize import Experiment

cloudpickle.register_pickle_by_value(rocket_target)
cloudpickle.register_pickle_by_value(sys.modules[__name__])


class RocketExperiment(Experiment):
    """Use the public single-core Rocket image and scalar-only workload flags."""

    def validate_hardware(self, hw: dict) -> None:
        """Require pinned Rocket source, build evidence and matching driver bytes."""
        rocket_target.validate_hardware(hw)

    def workload_flags(self) -> str:
        """Keep the fixed scalar ISA/ABI from Speckle; disable vectorization."""
        return rocket_target.SCALAR_FLAGS
