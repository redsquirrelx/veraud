"""Explicit public capability catalog, independent of runnable-agent discovery."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from .schemas import CoordinatorCapability


@dataclass(frozen=True)
class CoordinatorSpec:
    agent_class: type
    request_class: type
    capability: CoordinatorCapability
    result_kind: Literal["planning", "assessment"] = "planning"
    result_class: type | None = None


def registered_coordinators() -> dict[str, CoordinatorSpec]:
    from ..modularity.coordinator import (
        AssessmentRequest,
        AssessmentResult,
        ModularityCoordinator,
    )
    from ..modularity.coordinator.registry import (
        registered_investigators as modularity_investigators,
    )
    from ..reusability.coordinator import (
        ReusabilityCoordinator,
        ReusabilityRequest,
        ReusabilityResult,
    )
    from ..reusability.coordinator.registry import (
        registered_investigators as reusability_investigators,
    )

    investigators = modularity_investigators().values()
    capabilities = [spec.capability for spec in investigators]
    capability = CoordinatorCapability(id="modularity", agent_name="ModularityCoordinator",
        capability="Assess architecture through specialized investigators: " + " ".join(item.capability for item in capabilities),
        problem_types=sorted({problem for item in capabilities for problem in item.problem_types}),
        constraints=sorted({constraint for item in capabilities for constraint in item.constraints}))
    modularity_spec = CoordinatorSpec(ModularityCoordinator, AssessmentRequest, capability,
        result_kind="assessment", result_class=AssessmentResult)

    reusability_items = list(reusability_investigators().values())
    reusability_capability = CoordinatorCapability(id="reusability", agent_name="ReusabilityCoordinator",
        capability="Assess reusability through specialized investigators (none registered yet)." if not reusability_items
        else "Assess reusability through specialized investigators: " + " ".join(item.capability.capability for item in reusability_items),
        problem_types=sorted({problem for item in reusability_items for problem in item.capability.problem_types}),
        constraints=sorted({constraint for item in reusability_items for constraint in item.capability.constraints}))
    reusability_spec = CoordinatorSpec(ReusabilityCoordinator, ReusabilityRequest, reusability_capability,
        result_kind="assessment", result_class=ReusabilityResult)
    return {modularity_spec.capability.id: modularity_spec, reusability_spec.capability.id: reusability_spec}


def coordinator_catalog(capabilities: Iterable[CoordinatorCapability] | None = None) -> dict[str, CoordinatorCapability]:
    if capabilities is None:
        capabilities = [spec.capability for spec in registered_coordinators().values()]
    catalog = {}
    for value in capabilities:
        capability = CoordinatorCapability.model_validate(value)
        if capability.id in catalog:
            raise ValueError("Duplicate coordinator capability ID.")
        catalog[capability.id] = capability
    return dict(sorted(catalog.items()))
