"""Exact existing investigator contracts, not the BaseAgent HTTP registry."""

from dataclasses import dataclass

from ..architecture_boundary import ArchitectureBoundaryAgent, AuditRequest
from ..architecture_boundary import AuditResult as BoundaryResult
from ..dependency_impact import (
    DependencyImpactAgent,
    DependencyImpactRequest,
    DependencyImpactResult,
)
from ..responsibility import (
    ResponsibilityAgent,
    ResponsibilityRequest,
    ResponsibilityResult,
)
from .schemas import InvestigatorCapability


@dataclass(frozen=True)
class InvestigatorSpec:
    agent_class: type
    request_class: type
    result_class: type
    capability: InvestigatorCapability


INVESTIGATORS = {
    "architecture_boundary": InvestigatorSpec(ArchitectureBoundaryAgent, AuditRequest, BoundaryResult,
        InvestigatorCapability(id="architecture_boundary", agent_name="ArchitectureBoundaryAgent",
            capability="Investigate whether component dependencies respect explicit architectural boundaries and scoped design principles.")),
    "responsibility": InvestigatorSpec(ResponsibilityAgent, ResponsibilityRequest, ResponsibilityResult,
        InvestigatorCapability(id="responsibility", agent_name="ResponsibilityAgent",
            capability="Investigate coherent responsibilities, behavior placement and independent reasons for change.")),
    "dependency_impact": InvestigatorSpec(DependencyImpactAgent, DependencyImpactRequest, DependencyImpactResult,
        InvestigatorCapability(id="dependency_impact", agent_name="DependencyImpactAgent",
            capability="Investigate whether actual dependencies cause maintenance harm or concrete plausible change-propagation risks.")),
}
