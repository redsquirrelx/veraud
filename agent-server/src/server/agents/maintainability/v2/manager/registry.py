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


def selected_coordinators(request, capabilities: Iterable | None = None) -> dict[str, CoordinatorCapability]:
    """Deterministic coordinator selection for Maintainability V2.

    When the request carries `maintainability_selection`, the catalog seen by the
    planner is restricted to the selected coordinators (registered ids ∩
    selection), so no prompt instruction is required to keep the plan inside the
    user's choices. Without a selection, the registered catalog is returned as-is
    (legacy behavior for direct calls and tests).

    Legacy (full catalog, selection communicated via the objective prompt) is
    retained commented in manager/agent.py (LEGACY PROMPT MODE) and manager/execution.py,
    and documented in manager/README.md ("Modos de selección del coordinador").
    """
    catalog = coordinator_catalog(capabilities)
    selection = getattr(request, "maintainability_selection", None)
    if selection is None:
        return catalog
    return {key: capability for key, capability in catalog.items() if key in set(selection)}
