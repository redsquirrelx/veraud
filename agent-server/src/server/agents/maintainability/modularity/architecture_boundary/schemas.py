"""Boundary defaults and backward-compatible imports for shared audit contracts."""

from pydantic import Field

from config.agents import InvestigationConfig as BoundaryConfig

from .....runtimes.investigation.schemas import (
    AuditRequest as BaseAuditRequest,
)
from .....runtimes.investigation.schemas import (
    AuditResult,
    CandidateFinding,
    Contract,
    Criterion,
    Evaluation,
    EvidenceReference,
    Finding,
    FindingReview,
    Hypothesis,
    InvestigationPlan,
    Review,
)

__all__ = [
    "AuditRequest", "AuditResult", "BoundaryConfig", "CandidateFinding", "Contract", "Criterion",
    "Evaluation", "EvidenceReference", "Finding", "FindingReview", "Hypothesis", "InvestigationPlan", "Review",
]


class AuditRequest(BaseAuditRequest):
    objective: str = "Audit architectural boundaries and their impact on modularity."
    criteria: list[Criterion] = Field(default_factory=lambda: [Criterion(
        id="responsibility-boundaries", origin="design_principle",
        description="Keep responsibilities separated and dependencies aligned with declared component contracts.",
        provenance="Auditor design heuristic, not a normative ISO rule or a documented project constraint.",
    )], max_length=40)
