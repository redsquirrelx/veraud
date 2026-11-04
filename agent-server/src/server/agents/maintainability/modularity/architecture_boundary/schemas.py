"""Canonical contracts for this maintainability participant."""

from typing import ClassVar, Literal

from pydantic import ConfigDict, Field

from server.contracts.audit import (
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


class BoundarySupport(Contract):
    evidence_id: str
    role: Literal["declaration", "implementation", "usage", "composition", "dependency"]
    observation: str = Field(min_length=1, max_length=2000)
    symbol_id: str | None = Field(default=None,
        description="For behavior claims, identify the implemented function/method whose delivered body supports this specific observation, not the module's presumed purpose.")

class BoundaryVerification(Contract):
    dimension: Literal["dependency_direction", "shared_resources", "composition", "deployment"]
    evidence_ids: list[str] = Field(min_length=1, max_length=40)
    observation: str = Field(min_length=1, max_length=2000)

class BoundaryClaimCheck(Contract):
    subject_type: Literal["candidate", "hypothesis"]
    subject_id: str
    claim_kind: Literal["declaration", "behavior", "dependency", "isolation", "absence_of_cycles", "deployment"]
    scope_paths: list[str] = Field(min_length=1, max_length=40)
    support: list[BoundarySupport] = Field(min_length=1, max_length=80)
    coverage_complete: bool = False
    limitations: list[str] = Field(default_factory=list, max_length=20)
    verifications: list[BoundaryVerification] = Field(default_factory=list, max_length=8,
        description="For isolation: separately verify dependency direction, shared resources and composition. Deployment also needs deployment configuration. All entries cite delivered source, not an assertion of coverage.")

class BoundaryEvaluation(Evaluation):
    claim_checks: list[BoundaryClaimCheck] = Field(default_factory=list, max_length=60)
    validation_feedback: ClassVar[dict[str, str]] = Evaluation.validation_feedback | {
        "boundary_check_structure_invalid": "Return exactly one claim_check for every candidate and every confirmed/discarded hypothesis. Use exact subject IDs and real FILE paths, not directories. Repair the listed structural issues using delivered evidence; do not invent inspections. If evidence is lacking, retain an honest scoped candidate or unresolved hypothesis with sufficient=false and precise missing_information.",
        "too_short": "A required collection was empty. Every claim_check needs at least one scope_path and at least one support entry; every candidate needs at least one component and at least one evidence_id. An empty list is not a placeholder. If you did not inspect evidence that supports a subject, leave that hypothesis inconclusive and name the missing inspection in missing_information instead of asserting it.",
    }

class BoundaryFindingReview(FindingReview):
    scope_supported: bool = False
    checked_evidence_ids: list[str] = Field(default_factory=list, max_length=80)
    unverified_claims: list[str] = Field(default_factory=list, max_length=20)

class BoundaryHypothesisReview(Contract):
    hypothesis_id: str
    status: Literal["supported", "inconclusive"]
    rationale: str = Field(min_length=1, max_length=4000)
    scope_supported: bool = False
    checked_evidence_ids: list[str] = Field(default_factory=list, max_length=80)
    unverified_claims: list[str] = Field(default_factory=list, max_length=20)

class BoundaryReview(Review):
    findings: list[BoundaryFindingReview]
    hypotheses: list[BoundaryHypothesisReview] = Field(default_factory=list, max_length=60)
    validation_issues: list[str] = Field(default_factory=list)
    validation_feedback: ClassVar[dict[str, str]] = Review.validation_feedback | {
        "boundary_review_support_required": "An accepted boundary candidate requires scope_supported=true, no unverified_claims, and checked_evidence_ids covering every support item in its claim_check. Otherwise mark insufficient_evidence or rejected; do not invent verification.",
    }

class BoundaryFinding(Finding):
    claim_check: BoundaryClaimCheck | None = None
    validation_issues: list[str] = Field(default_factory=list)

class BoundaryResult(AuditResult):
    findings: list[BoundaryFinding]
    request_fingerprint: str = ""
    investigation_coverage: dict = Field(default_factory=dict,
        description="Host-derived indexed boundary coverage; navigation and inspected endpoints, not proof of isolation.")
    claim_checks: list[BoundaryClaimCheck] = Field(default_factory=list)
    critical_review: BoundaryReview | None = None
    failed_evaluation_attempt: BoundaryEvaluation | None = None
    evaluation_attempt_issues: list[dict[str, str]] = Field(default_factory=list)
    evaluation_evidence_status: Literal["not_evaluated", "current", "stale"] = "not_evaluated"
    evaluated_evidence_ids: list[str] = Field(default_factory=list,
        description="Delivered evidence available to the last structurally valid evaluation; not necessarily cited or verified.")
    pending_evaluation_evidence_ids: list[str] = Field(default_factory=list,
        description="Retained evidence not available to that evaluation. Its presence does not update prior conclusions.")
    investigation_tasks: list[dict] = Field(default_factory=list)
    investigation_progress: list[dict] = Field(default_factory=list)
    consumption_by_phase: dict[str, dict[str, int]] = Field(default_factory=dict)
    continuation_usage: dict[str, int] = Field(default_factory=dict,
        description="Previous execution usage, kept separate from this run's counters.")

class ArchitectureBoundaryRequest(AuditRequest):
    model_config = ConfigDict(title="AuditRequest")

    objective: str = "Audit architectural boundaries and their impact on modularity."
    continuation: BoundaryResult | None = Field(default=None,
        description="Prior result for the exact same snapshot, commit, objective and criteria. Source is re-delivered through bounded repository tools and conclusions revalidated; previous usage stays separate.")
    criteria: list[Criterion] = Field(default_factory=lambda: [Criterion(
        id="responsibility-boundaries", origin="design_principle",
        description="Keep responsibilities separated and dependencies aligned with declared component contracts.",
        provenance="Auditor design heuristic, not a normative ISO rule or a documented project constraint.",
    )], max_length=40)

from config.agents import InvestigationConfig as BoundaryConfig

__all__ = ['AuditRequest', 'AuditResult', 'BaseAuditRequest', 'BoundaryClaimCheck', 'BoundaryConfig', 'BoundaryEvaluation', 'BoundaryFinding', 'BoundaryFindingReview', 'BoundaryReview', 'BoundarySupport', 'CandidateFinding', 'Contract', 'Criterion', 'Evaluation', 'EvidenceReference', 'Finding', 'FindingReview', 'Hypothesis', 'InvestigationPlan', 'Review']

BaseAuditRequest = AuditRequest
AuditRequest = ArchitectureBoundaryRequest
AuditResult = BoundaryResult
