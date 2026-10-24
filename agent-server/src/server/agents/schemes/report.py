"""Versioned, attribute-neutral JSON document for formal software audit reporting."""

from datetime import datetime
from typing import Literal

from pydantic import Field, JsonValue

from ...services.audit_diagnostics import ExecutionDiagnostic
from .base import Contract, Criterion

ReportStatus = Literal["completed", "partial", "failed"]
EvaluationStatus = Literal["completed", "partial", "failed", "not_evaluated"]
VerificationStatus = Literal["verified", "inconclusive", "discarded"]


class AuditReportRequest(Contract):
    run_id: str = Field(min_length=1, pattern=r"\S")


class RecordReference(Contract):
    record_type: Literal["finding", "assessment", "evidence"]
    record_id: str
    agent_id: str
    invocation_id: str


class ReportStatement(Contract):
    text: str
    source_refs: list[RecordReference] = Field(default_factory=list)


class RepositoryRevision(Contract):
    repository_id: str | None
    commit: str | None
    snapshot_hash: str


class ReportIdentification(Contract):
    title: str = "Informe de auditoría de calidad del software"
    audit_id: str
    project_name: str | None
    repository_location: str | None
    repository_url: str | None
    revisions: list[RepositoryRevision]
    executed_at: datetime | None
    issued_at: datetime
    status: ReportStatus
    source_digest: str


class FindingStatistics(Contract):
    counting_basis: Literal["blackboard_finding_records"] = "blackboard_finding_records"
    total: int = 0
    by_severity: dict[str, int] = Field(default_factory=dict)
    by_verification: dict[str, int] = Field(default_factory=dict)
    by_severity_and_verification: dict[str, dict[str, int]] = Field(default_factory=dict)
    by_attribute: dict[str, int] = Field(default_factory=dict)
    verified_by_component: dict[str, int] = Field(default_factory=dict)
    active_total: int = 0
    active_by_verification: dict[str, int] = Field(default_factory=dict)


class ExecutiveSummary(Contract):
    objective: list[ReportStatement]
    evaluated_attributes: list[str]
    principal_results: list[ReportStatement]
    findings: FindingStatistics
    principal_risk_ids: list[str]
    conclusion: str


class AuditScope(Contract):
    general_objectives: list[ReportStatement]
    specific_objectives: list[ReportStatement]
    attributes_and_subcharacteristics: dict[str, list[str]]
    included_components: list[str]
    inspected_files: list[str]
    declared_targets: list[str]
    exclusions: list[str]
    limitations: list[str]


class AuditMethodology(Contract):
    quality_model: str = "ISO/IEC 25010:2023 (modelo de referencia; no certificación de conformidad)"
    applied_criteria: list[Criterion]
    static_analysis: list[str]
    dynamic_analysis: list[ReportStatement]
    tools: list[str]
    finding_validation: list[str]
    severity_criteria: dict[str, str]
    limitations: list[str]


class SoftwareDescription(Contract):
    description: ReportStatement | None = None
    languages: list[str] = Field(default_factory=list)
    technologies: list[dict[str, JsonValue]] = Field(default_factory=list)
    repository_structure: list[str] = Field(default_factory=list)
    modules: list[str] = Field(default_factory=list)
    architecture: list[ReportStatement] = Field(default_factory=list)
    dependencies: list[dict[str, JsonValue]] = Field(default_factory=list)
    runtime_environment: list[dict[str, JsonValue]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    source_refs: list[RecordReference] = Field(default_factory=list)


class ReportQualifications(Contract):
    assessed_context: str = ""
    sharing_boundary: str = ""
    conditions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ReportFinding(ReportQualifications):
    id: str
    title: str
    quality_attribute: str
    subcharacteristic: str
    kind: Literal["violation", "design_observation"]
    severity: Literal["info", "low", "medium", "high", "critical"] | None
    description: str
    criterion: Criterion
    justification: str
    evidence_ids: list[str]
    components: list[str]
    impact: str
    recommendation: str | None
    verification_status: VerificationStatus
    verification_rationale: str
    validation_issues: list[str]
    source_refs: list[RecordReference]
    consolidation_ids: list[str] = Field(default_factory=list)
    classification: Literal["problem", "observation", "strength"] = "observation"
    technical_details: dict[str, JsonValue] = Field(default_factory=dict)
    lifecycle: Literal["current", "historical"] = "current"
    superseded_by: list[str] = Field(default_factory=list)
    original_validation_status: str = "insufficient_evidence"
    original_review_rationale: str = ""
    disposition: Literal["defect", "contextual_risk", "opportunity", "conditional_proposal", "strength", "observation"] = "observation"


class SubcharacteristicResult(Contract):
    id: str
    title: str
    status: EvaluationStatus
    evaluation_topics: list[str]
    assessments: list[ReportStatement]
    finding_ids: list[str]
    conclusion: str
    limitations: list[str]


class AttributeResult(Contract):
    id: str
    title: str
    status: EvaluationStatus
    summary: list[ReportStatement]
    subcharacteristics: list[SubcharacteristicResult]
    conclusion: str


class QualityResults(Contract):
    attributes: list[AttributeResult]
    findings: list[ReportFinding]


class ReportRisk(ReportQualifications):
    id: str
    finding_ids: list[str]
    components: list[str]
    description: str
    severity: str | None
    priority: Literal["urgent", "high", "medium", "low", "undetermined"]
    basis: Literal["verified_findings"] = "verified_findings"
    risk_type: Literal["verified_harm", "contextual"] = "verified_harm"


class FindingRelationship(Contract):
    kind: str
    finding_ids: list[str]
    rationale: str
    status: str
    source_refs: list[RecordReference]


class ConsolidatedRiskAnalysis(Contract):
    findings: FindingStatistics
    risks: list[ReportRisk]
    relationships: list[FindingRelationship]
    prioritization_method: str


class AuditConclusions(Contract):
    by_attribute: list[ReportStatement]
    strengths: list[ReportStatement]
    weaknesses: list[ReportStatement]
    critical_finding_ids: list[str]
    limitations: list[str]
    general_conclusion: str


class ImprovementRecommendation(ReportQualifications):
    id: str
    finding_ids: list[str]
    action: str
    technical_justification: str
    priority: Literal["urgent", "high", "medium", "low", "undetermined"]
    expected_benefit: str
    proposed_verification_criterion: str
    action_type: Literal["correction", "context_validation", "opportunity_assessment", "conditional_assessment"] = "correction"


class ReportEvidence(Contract):
    id: str
    kind: str
    source: str
    content: str | None
    snapshot_hash: str
    commit: str | None
    commit_verification: str | None
    git_blob_id: str | None
    file_id: str
    content_hash: str
    symbol_ids: list[str]
    start_line: int | None
    end_line: int | None
    tool_call_id: str
    provenance: RecordReference


class ExecutionTrace(Contract):
    agent_id: str
    invocation_id: str
    assessment_ids: list[str]
    status: str | None
    termination_reason: str | None
    consumption: dict[str, JsonValue]
    limitations: list[str]
    unresolved_results: list[dict[str, JsonValue]]
    recorded_results: dict[str, JsonValue] = Field(default_factory=dict)


class CoverageCommitment(Contract):
    invocation_id: str
    agent_id: str
    hypothesis_id: str | None = None
    question: str
    subject_ids: list[str] = Field(default_factory=list)
    status: Literal["evaluated", "discarded", "pending", "deferred", "skipped", "not_evaluated"]
    final_hypothesis_status: str | None = None
    assessment_ids: list[str] = Field(default_factory=list)
    validation_issues: list[str] = Field(default_factory=list)
    source_refs: list[RecordReference] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    lifecycle: Literal["current", "historical"] = "current"


class ReportDecision(Contract):
    id: str
    rule: str
    outcome: str
    reason: str
    source_refs: list[RecordReference] = Field(default_factory=list)
    output_paths: list[str] = Field(default_factory=list)


class ReportGeneration(Contract):
    generation_id: str
    generator_version: str
    report_schema_version: str = "1.0"
    generated_at: datetime
    source_digest: str
    source_snapshot: dict[str, JsonValue]
    effective_assessment_ids: list[str]
    historical_assessment_ids: list[str]
    decisions: list[ReportDecision]
    validation_status: Literal["pending", "passed", "failed"] = "pending"
    validation_checks: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


class ReportGenerationSummary(Contract):
    generation_id: str
    generated_at: datetime
    generator_version: str
    source_digest: str
    validation_status: Literal["pending", "passed", "failed"]


class AuditAnnexes(Contract):
    reference_labels: dict[str, str] = Field(default_factory=dict)
    evidence_inventory: list[ReportEvidence]
    assessments: list[RecordReference]
    executions: list[ExecutionTrace]
    metrics_and_tool_results: list[dict[str, JsonValue]]
    diagrams_and_graphs: list[dict[str, JsonValue]]
    participants: list[str]
    tools: list[str]
    tool_call_ids: list[str]
    additional_criteria: list[Criterion]
    unresolved_references: list[str]
    limitations: list[str]
    execution_issues: list[ExecutionDiagnostic] = Field(default_factory=list)
    coverage_commitments: list[CoverageCommitment] = Field(default_factory=list)
    generation: ReportGeneration | None = None


class SoftwareAuditReport(Contract):
    schema_version: Literal["1.0"] = "1.0"
    language: Literal["es"] = "es"
    identification: ReportIdentification
    executive_summary: ExecutiveSummary
    objectives_and_scope: AuditScope
    methodology_and_criteria: AuditMethodology
    software_description: SoftwareDescription
    quality_results: QualityResults
    consolidated_risks: ConsolidatedRiskAnalysis
    general_conclusions: AuditConclusions
    recommendations_and_improvement_plan: list[ImprovementRecommendation]
    annexes_and_traceability: AuditAnnexes
