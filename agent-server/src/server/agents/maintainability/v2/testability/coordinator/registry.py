"""V2 testability investigator registrations.

The documentary test-isolation and test-controllability investigators are
registered here. Investigator IDs are the keys seen by `maintainability_selection`,
the agent catalog and the configuration panel.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from .schemas import InvestigatorCapability


@dataclass(frozen=True)
class InvestigatorSpec:
    agent_class: type
    request_class: type
    result_class: type
    capability: InvestigatorCapability
    completed_reasons: tuple[str, ...] = ("sufficient_evidence",)


def registered_investigators() -> dict[str, InvestigatorSpec]:
    from ..test_controllability_doc_driven import (
        TestControllabilityAgent,
        TestControllabilityRequest,
        TestControllabilityResult,
    )
    from ..test_isolation_doc_driven import (
        TestIsolationAgent,
        TestIsolationRequest,
        TestIsolationResult,
    )

    isolation_capability = InvestigatorCapability(
        id="test_isolation",
        agent_name="TestIsolationAgent",
        capability="Investigate whether components can be isolated from their dependencies for independent testing.",
        problem_types=["hidden dependencies", "global state", "concrete constructions",
            "uncontrolled external effects", "non-determinism"],
        constraints=[
            "Documentation is orientation context, not implementation evidence.",
            "The investigator uses its internal task; external objectives are not forwarded as instructions.",
        ],
    )
    isolation_spec = InvestigatorSpec(TestIsolationAgent, TestIsolationRequest, TestIsolationResult, isolation_capability,
        completed_reasons=("investigations_completed", "sufficient_evidence"))

    controllability_capability = InvestigatorCapability(
        id="test_controllability",
        agent_name="TestControllabilityAgent",
        capability="Investigate whether components allow the entries, states, dependencies and conditions needed to test their documented behaviors to be controlled.",
        problem_types=["uncontrollable time", "non-determinism", "inducible failures",
            "shared state", "uncontrolled concurrency", "fixed configuration", "external effects"],
        constraints=[
            "Documentation is orientation context, not implementation evidence.",
            "The investigator uses its internal task; external objectives are not forwarded as instructions.",
        ],
    )
    controllability_spec = InvestigatorSpec(TestControllabilityAgent, TestControllabilityRequest,
        TestControllabilityResult, controllability_capability,
        completed_reasons=("investigations_completed", "sufficient_evidence"))

    return {isolation_capability.id: isolation_spec, controllability_capability.id: controllability_spec}


def investigator_catalog(capabilities: Iterable[InvestigatorCapability] | None = None) -> dict[str, InvestigatorCapability]:
    registered = registered_investigators()
    if capabilities is None:
        capabilities = [spec.capability for spec in registered.values()]
    catalog = {}
    for value in capabilities:
        capability = InvestigatorCapability.model_validate(value)
        if capability.id not in registered:
            raise ValueError("Investigator capability is not registered.")
        if capability.id in catalog:
            raise ValueError("Duplicate investigator capability ID.")
        catalog[capability.id] = capability
    return dict(sorted(catalog.items()))
