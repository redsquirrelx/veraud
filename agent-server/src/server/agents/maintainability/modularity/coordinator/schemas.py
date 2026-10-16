"""Compatibility exports for modularity coordinator contracts."""

from config.agents import CoordinatorConfig as ModularityConfig

from ....schemes.coordinator import (
    Assignment,
    AuditRequest,
    AuditResult,
    ConsolidatedFinding,
    Consumption,
    Contract,
    EvidenceGap,
    EvidenceReference,
    ExecutionBudget,
    Finding,
    FindingContribution,
    FindingGroup,
    GapResolution,
    InvestigatorCapability,
    InvestigatorId,
    InvocationRecord,
    ModularityAssessment,
    ModularityRequest,
    ProposedGap,
    RawInvocation,
    Route,
    SynthesisDraft,
)

__all__ = [
    "Assignment", "AuditRequest", "AuditResult", "ConsolidatedFinding", "Consumption", "Contract", "EvidenceGap",
    "EvidenceReference", "ExecutionBudget", "Finding", "FindingContribution", "FindingGroup", "GapResolution",
    "InvestigatorCapability", "InvestigatorId", "InvocationRecord", "ModularityAssessment", "ModularityConfig",
    "ModularityRequest", "ProposedGap", "RawInvocation", "Route", "SynthesisDraft",
]
