"""V2 documentary-boundary binding only; no V1 investigators are imported."""

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
    from ..architecture_boundary_doc_driven import (
        ArchitectureBoundaryAgent,
        AuditRequest,
    )
    from ..architecture_boundary_doc_driven.schemas import BoundaryResult
    from ..responsibility_doc_driven import (
        AuditRequest as ResponsibilityAuditRequest,
    )
    from ..responsibility_doc_driven import (
        ResponsibilityAgent,
    )
    from ..responsibility_doc_driven.schemas import ResponsibilityResult

    specs = [
        InvestigatorSpec(ArchitectureBoundaryAgent, AuditRequest, BoundaryResult,
            InvestigatorCapability(id="architecture_boundary", agent_name="ArchitectureBoundaryAgent",
                capability="Investigate component interactions against explicit architectural boundaries, scoped design principles and supplied documentary obligations.",
                problem_types=["architectural boundary violations", "documented architectural obligations"],
                constraints=["Documentation defines obligations, not implementation evidence.",
                    "The investigator follows its internal task only; external objectives and free-form context are not forwarded. Supply scope through structured targets.",
                    "Local compatibility does not establish repository-wide compliance."]),
            completed_reasons=("investigations_completed", "sufficient_evidence")),
        InvestigatorSpec(ResponsibilityAgent, ResponsibilityAuditRequest, ResponsibilityResult,
            InvestigatorCapability(id="responsibility", agent_name="ResponsibilityAgent",
                capability="Investigate whether classes and components hold single cohesive responsibilities, contrasting documented purposes with implemented operations and independent reasons to change.",
                problem_types=["single-responsibility violations", "component cohesion"],
                constraints=["Documentation defines purposes, not implementation evidence.",
                    "The investigator follows its internal task only; external objectives and free-form context are not forwarded. Supply scope through structured targets.",
                    "Local compatibility does not establish repository-wide compliance."]),
            completed_reasons=("investigations_completed", "sufficient_evidence")),
    ]
    return {spec.capability.id: spec for spec in sorted(specs, key=lambda spec: spec.capability.id)}


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
