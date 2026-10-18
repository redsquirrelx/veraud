"""Compatibility exports for the canonical investigator contracts."""

from config.agents import InvestigationConfig as ResponsibilityConfig

from ....schemes.investigator import (
    AuditRequest,
    AuditResult,
    CandidateFinding,
    ComponentAssessment,
    Contract,
    Criterion,
    Evaluation,
    EvidenceReference,
    Finding,
    Hypothesis,
    InvestigatedComponent,
    Responsibility,
    ResponsibilityCandidate,
    ResponsibilityConflict,
    ResponsibilityEvaluation,
    ResponsibilityFinding,
    ResponsibilityRequest,
    ResponsibilityResult,
    ResponsibilityReview,
)
from ....schemes.investigator import (
    responsibility_criteria as default_criteria,
)

__all__ = [
    "AuditRequest", "AuditResult", "CandidateFinding", "ComponentAssessment", "Contract", "Criterion",
    "Evaluation", "EvidenceReference", "Finding", "Hypothesis", "InvestigatedComponent", "Responsibility",
    "ResponsibilityCandidate", "ResponsibilityConfig", "ResponsibilityConflict", "ResponsibilityEvaluation",
    "ResponsibilityFinding", "ResponsibilityRequest", "ResponsibilityResult", "ResponsibilityReview", "default_criteria",
]
