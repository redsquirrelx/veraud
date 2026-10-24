"""Compatibility exports for dependency-impact contracts."""

from ....schemes.investigator import (
    AuditRequest,
    AuditResult,
    CandidateFinding,
    Contract,
    Criterion,
    DependencyAssessment,
    DependencyImpactCandidate,
    DependencyImpactEvaluation,
    DependencyImpactFinding,
    DependencyImpactRequest,
    DependencyImpactResult,
    DependencyImpactReview,
    DependencyLink,
    Evaluation,
    EvidenceReference,
    Finding,
    FindingBasis,
    Hypothesis,
    ImpactKind,
    InvestigatedDependency,
    InvestigatedImpact,
)
from ....schemes.investigator import (
    DependencyComponentReference as ComponentReference,
)
from ....schemes.investigator import (
    dependency_impact_criteria as default_criteria,
)
from .config import DependencyImpactConfig

__all__ = [
    "AuditRequest", "AuditResult", "CandidateFinding", "ComponentReference", "Contract", "Criterion",
    "DependencyAssessment", "DependencyImpactCandidate", "DependencyImpactConfig", "DependencyImpactEvaluation",
    "DependencyImpactFinding", "DependencyImpactRequest", "DependencyImpactResult", "DependencyImpactReview", "DependencyLink", "Evaluation",
    "EvidenceReference", "Finding", "FindingBasis", "Hypothesis", "ImpactKind", "InvestigatedDependency",
    "InvestigatedImpact", "default_criteria",
]
