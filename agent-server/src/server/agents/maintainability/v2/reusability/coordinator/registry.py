"""V2 reusability investigator registrations; V1 investigators are not imported."""

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
    from ..abstraction_doc_driven import AbstractionAgent, AbstractionRequest
    from ..abstraction_doc_driven.schemas import AbstractionResult
    from ..reuse_opportunity_doc_driven import (
        ReuseOpportunityDocDrivenAgent,
        ReuseOpportunityDocDrivenRequest,
        ReuseOpportunityDocDrivenResult,
    )
    from ..reuse_parametrization_doc_driven import (
        ReuseParametrizationDocDrivenAgent,
        ReuseParametrizationDocDrivenRequest,
        ReuseParametrizationDocDrivenResult,
    )

    capability = InvestigatorCapability(id="abstraction", agent_name="AbstractionAgent",
        capability="Investigate abstraction and reuse opportunities supported by source evidence.",
        problem_types=["abstraction opportunities", "duplicated reusable behavior", "overly specific implementations"],
        constraints=["Documentation describes intended abstraction, not implementation evidence.",
            "The investigator uses its internal task; external objectives are not forwarded as instructions."])
    spec = InvestigatorSpec(AbstractionAgent, AbstractionRequest, AbstractionResult, capability,
        completed_reasons=("investigations_completed", "sufficient_evidence"))
    reuse_capability = InvestigatorCapability(
        id="reuse_opportunity_doc_driven",
        agent_name="ReuseOpportunityDocDrivenAgent",
        capability="Investigate source-supported reuse opportunities with documentary context available.",
        problem_types=["reuse opportunities", "repeated behavior", "reusable implementations"],
        constraints=[
            "Documentary context is input context, not implementation evidence.",
            "This investigator currently performs planning only; implementation evidence and findings are not produced.",
        ],
    )
    reuse_spec = InvestigatorSpec(
        ReuseOpportunityDocDrivenAgent,
        ReuseOpportunityDocDrivenRequest,
        ReuseOpportunityDocDrivenResult,
        reuse_capability,
        completed_reasons=(),
    )
    parametrization_capability = InvestigatorCapability(
        id="reuse_parametrization_doc_driven",
        agent_name="ReuseParametrizationDocDrivenAgent",
        capability="Plan source-supported opportunities to parametrize reusable behavior, with documentary context available.",
        problem_types=["parametrized reuse", "shared behavior parameters", "reusable implementation settings"],
        constraints=[
            "Documentary context is input context, not implementation evidence.",
            "This investigator currently performs planning only; implementation evidence and findings are not produced.",
        ],
    )
    parametrization_spec = InvestigatorSpec(
        ReuseParametrizationDocDrivenAgent,
        ReuseParametrizationDocDrivenRequest,
        ReuseParametrizationDocDrivenResult,
        parametrization_capability,
        completed_reasons=(),
    )
    return {
        capability.id: spec,
        reuse_capability.id: reuse_spec,
        parametrization_capability.id: parametrization_spec,
    }


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
