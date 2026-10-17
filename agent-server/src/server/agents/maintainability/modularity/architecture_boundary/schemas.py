"""Compatibility exports for architecture-boundary contracts."""

from config.agents import InvestigationConfig as BoundaryConfig

from ....schemes.base import AuditRequest as BaseAuditRequest
from ....schemes.base import FindingReview, InvestigationPlan, Review
from ....schemes.investigator import (
    ArchitectureBoundaryRequest as AuditRequest,
)
from ....schemes.investigator import (
    BoundaryClaimCheck,
    BoundaryEvaluation,
    BoundaryFinding,
    BoundaryFindingReview,
    BoundaryReview,
    BoundarySupport,
    CandidateFinding,
    Contract,
    Criterion,
    Evaluation,
    EvidenceReference,
    Finding,
    Hypothesis,
)
from ....schemes.investigator import (
    BoundaryResult as AuditResult,
)

__all__ = [
    "AuditRequest", "AuditResult", "BaseAuditRequest", "BoundaryClaimCheck", "BoundaryConfig", "BoundaryEvaluation",
    "BoundaryFinding", "BoundaryFindingReview", "BoundaryReview", "BoundarySupport", "CandidateFinding", "Contract", "Criterion",
    "Evaluation", "EvidenceReference", "Finding", "FindingReview", "Hypothesis", "InvestigationPlan", "Review",
]
