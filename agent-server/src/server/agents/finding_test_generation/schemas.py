"""Typed contracts for the finding-test generation prototype.

These schemas describe the audit input, the intermediate verification plan,
the exported suite manifest and the outcome of a generation run. They are
deliberately independent of the runtime graph so they can be reused by the
CLI, the packaging step and, later, the integration adapter.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Strategy = Literal["static_ast", "dynamic_mock", "hybrid"]
Language = Literal["python", "typescript", "javascript"]

VerificationStatus = Literal[
    "VIOLATION_PRESENT",
    "VERIFIED_FIXED",
    "INCONCLUSIVE",
    "EXECUTION_ERROR",
    "NOT_VERIFIABLE",
]

GenerationStatus = Literal[
    "generated",
    "validated_red",
    "validated_red_green",
    "partially_validated",
    "not_verifiable",
    "environment_blocked",
    "invalid",
]


class _Loose(BaseModel):
    """Preserves members unknown to the prototype instead of dropping them."""

    model_config = ConfigDict(extra="allow")


class Criterion(_Loose):
    id: str
    description: str = ""
    origin: str | None = None
    provenance: str | None = None


class DocumentaryReference(_Loose):
    document_claim_id: str
    subject: str = ""
    statement: str = ""
    constraint: str = ""
    certainty: str = ""
    section_paths: dict[str, str] = Field(default_factory=dict)
    status: str = ""
    commit: str | None = None


class TechnicalDetails(_Loose):
    id: str
    title: str = ""
    description: str = ""
    kind: str = ""
    criterion_id: str = ""
    components: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    justification: str = ""
    recommendation: str = ""
    confidence: float | None = None
    document_claim_ids: list[str] = Field(default_factory=list)
    documentary_references: list[DocumentaryReference] = Field(default_factory=list)
    validation_issues: list[str] = Field(default_factory=list)


class SourceRef(_Loose):
    record_type: str = ""
    record_id: str
    agent_id: str | None = None
    invocation_id: str | None = None


class Finding(_Loose):
    id: str
    title: str
    quality_attribute: str = ""
    subcharacteristic: str = ""
    kind: str = ""
    severity: str = ""
    description: str = ""
    criterion: Criterion
    justification: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    components: list[str] = Field(default_factory=list)
    impact: str = ""
    recommendation: str = ""
    verification_status: str = "unreviewed"
    verification_rationale: str = ""
    validation_issues: list[str] = Field(default_factory=list)
    source_refs: list[SourceRef] = Field(default_factory=list)
    consolidation_ids: list[str] = Field(default_factory=list)
    classification: str = ""
    technical_details: TechnicalDetails
    lifecycle: str = ""
    superseded_by: list[str] = Field(default_factory=list)
    original_validation_status: str | None = None
    original_review_rationale: str = ""
    disposition: str = ""


class AuditDocument(BaseModel):
    """Root of an audit export, e.g. ``hallazgos-auditoria-140.json``."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    audit_id: int = Field(alias="auditId")
    commit_hash: str = Field(alias="commitHash")
    attributes: list[str] = Field(default_factory=list)
    exported_at: str | None = Field(default=None, alias="exportedAt")
    findings: list[Finding] = Field(default_factory=list)


class RuleSource(BaseModel):
    document_claim_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class VerificationSpec(BaseModel):
    """A single verifiable obligation derived from a finding.

    This is a plan, not code and not evidence of execution.
    """

    finding_id: str
    verification_id: str
    title: str
    rule_source: RuleSource
    target_components: list[str]
    property: str
    strategy: Strategy
    scenarios: list[str] = Field(default_factory=list)
    violation_oracle: str
    fixed_oracle: str
    limits: list[str] = Field(default_factory=list)
    source_scope: str
    test_scenario_scope: str
    test_path: str
    test_name: str
    rule_kind: str | None = None
    rule_params: dict[str, object] = Field(default_factory=dict)
    language: Language = "python"


class ValidationRecord(BaseModel):
    verification_id: str
    status: GenerationStatus
    notes: list[str] = Field(default_factory=list)


class VerificationResult(BaseModel):
    verification_id: str
    finding_id: str
    status: VerificationStatus
    summary: str = ""
    evidence: list[str] = Field(default_factory=list)


class ManifestVerification(BaseModel):
    finding_id: str
    verification_id: str
    test_path: str
    test_name: str
    strategy: Strategy
    covered_property: str
    target_components: list[str]
    document_claim_ids: list[str] = Field(default_factory=list)
    rule_id: str | None = None
    rule_params: dict[str, object] = Field(default_factory=dict)
    generated_by: str | None = None
    generation_status: GenerationStatus = "generated"
    coverage_limitations: list[str] = Field(default_factory=list)
    language: Language = "python"
    framework: str = "pytest"


class VerificationSuiteManifest(BaseModel):
    schema_version: str = "1.0"
    audit_id: int
    source_commit: str
    suite_id: str
    generator_version: str
    project_language: str = "python"
    runner: str = "uv"
    root_layout: str = ".tallercito"
    documentary_references: list[dict] = Field(default_factory=list)
    verifications: list[ManifestVerification] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class FindingTestGenerationRequest(BaseModel):
    """Input contract: an audit export, an optional checkout and a destination."""

    findings_path: str
    repo_path: str | None = None
    output_path: str


class FindingTestGenerationResult(BaseModel):
    """Outcome of one generation run, before any local execution."""

    ok: bool
    termination_reason: str
    llm_tokens: int | None = None
    suite_id: str = ""
    audit_id: int | None = None
    source_commit: str = ""
    output_zip: str | None = None
    specs: list[VerificationSpec] = Field(default_factory=list)
    validation_records: list[ValidationRecord] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    baseline_available: bool = False
    verification_results: list[VerificationResult] = Field(default_factory=list)
    validation_status: str = "not_run"  # not_run | validated | partial | environment_blocked | invalid
