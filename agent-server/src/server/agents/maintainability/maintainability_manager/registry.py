"""Public coordinator interfaces; no investigator logic at manager level."""

from dataclasses import dataclass

from ..modularity import ModularityAgent, ModularityConfig, ModularityRequest
from ..reusability import ReusabilityAgent, ReusabilityConfig, ReusabilityRequest
from ..reusability.schemas import ReusabilityAssessment
from .schemas import NestedModularityAssessment


@dataclass(frozen=True)
class CoordinatorSpec:
    agent_class: type
    request_class: type
    result_class: type
    config_class: type


COORDINATORS = {
    "modularity": CoordinatorSpec(ModularityAgent, ModularityRequest, NestedModularityAssessment, ModularityConfig),
    "reusability": CoordinatorSpec(ReusabilityAgent, ReusabilityRequest, ReusabilityAssessment, ReusabilityConfig),
}
