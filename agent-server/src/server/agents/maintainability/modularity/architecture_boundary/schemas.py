"""Compatibility exports for architecture-boundary contracts."""

from config.agents import InvestigationConfig as BoundaryConfig

from ....schemes.base import AuditRequest as BaseAuditRequest
from ....schemes.base import FindingReview, InvestigationPlan, Review
from ....schemes.investigator import (
    ArchitectureBoundaryRequest as AuditRequest,
)
from ....schemes.investigator import (
    AuditResult,
    CandidateFinding,
    Contract,
    Criterion,
    Evaluation,
    EvidenceReference,
    Finding,
    Hypothesis,
)

__all__ = [
    "AuditRequest", "AuditResult", "BaseAuditRequest", "BoundaryConfig", "CandidateFinding", "Contract", "Criterion",
    "Evaluation", "EvidenceReference", "Finding", "FindingReview", "Hypothesis", "InvestigationPlan", "Review",
]
