"""Compatibility exports for the canonical domain-independent agent contracts."""

from config.agents import InvestigationConfig, ProviderRateLimits

from ...agents.schemes.base import (
    AuditRequest,
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
    "AuditRequest", "AuditResult", "CandidateFinding", "Contract", "Criterion", "Evaluation", "EvidenceReference",
    "Finding", "FindingReview", "Hypothesis", "InvestigationConfig", "InvestigationPlan", "ProviderRateLimits", "Review",
]
