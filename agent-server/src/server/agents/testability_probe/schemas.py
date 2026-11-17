"""Typed contracts for the TestabilityProbeAgent.

Input findings come from the testability investigations (TestIsolationAgent /
TestControllabilityAgent) persisted as their result JSON (``*-NNN.json`` under
``artifacts/``). The portable deliverable is a ``.tallercito/`` ZIP whose
``manifest.json`` stays compatible with the shared runner (field names
``audit_id`` / ``source_commit`` / ``verification_id`` / ``finding_id`` /
``test_path`` / ``strategy`` / ``covered_property`` / ``target_components``).

Generation states (``generated`` / ``invalid``) are tracked separately from
execution outcomes (``violation_present`` / ``execution_error`` / ...). A test
that was correctly generated says nothing about whether the finding is fixed.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

GENERATOR_ID = "testability-probe"
GENERATOR_VERSION = "testability-probe-0.1"
MANIFEST_SCHEMA_VERSION = "1.1"


class _Loose(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class ProbeFindingEvidence(_Loose):
    id: str = ""
    kind: str = ""
    path: str = ""
    start_line: int | None = None
    end_line: int | None = None
    symbol_ids: list[str] = Field(default_factory=list)
    commit: str = ""
    snapshot_hash: str = ""
    file_id: str = ""
    content_hash: str = ""
    commit_verification: str = ""


class ProbeFinding(_Loose):
    id: str
    title: str = ""
    description: str = ""
    criterion_id: str = ""
    kind: str = ""
    components: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    justification: str = ""
    modularity_impact: str = ""
    severity: str = ""
    confidence: float = 0.0
    recommendation: str = ""
    document_claim_ids: list[str] = Field(default_factory=list)
    evidence: list[ProbeFindingEvidence] = Field(default_factory=list)
    validation_status: str = ""


class ProbeDocument(_Loose):
    """Lenient view of a TestIsolation/TestControllability result export."""

    repository_id: str = ""
    commit: str = ""
    snapshot_hash: str = ""
    objective: str = ""
    findings: list[ProbeFinding] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    termination_reason: str = ""


class VerificationPlanItem(_Loose):
    """One concrete verification planned by the LLM (validated)."""

    title: str = ""
    condition: str = ""
    strategy: Literal["static_ast", "dynamic_mock", "behavioral", "structural"] = "structural"
    target_components: list[str] = Field(default_factory=list)
    property: str = ""
    scenarios: list[str] = Field(default_factory=list)
    violation_oracle: str = ""
    fixed_oracle: str = ""
    limits: list[str] = Field(default_factory=list)
    test_name: str = ""
    framework: Literal["pytest", "vitest", "node:test"] | None = None


class PlannedVerification(BaseModel):
    """A verification ready for code generation."""

    verification_id: str
    finding_id: str
    title: str
    condition: str
    strategy: str
    target_components: list[str]
    property: str
    scenarios: list[str]
    violation_oracle: str
    fixed_oracle: str
    limits: list[str]
    test_path: str
    test_name: str
    evidence_refs: list[str] = Field(default_factory=list)
    language: str = "python"
    framework: str = "pytest"


class ValidationRecord(BaseModel):
    verification_id: str
    finding_id: str
    status: Literal[
        "generated", "invalid", "validated_red", "validated_red_green",
        "partially_validated", "environment_blocked", "not_generated",
    ]
    detail: str = ""
    attempts: int = 1


class VerificationResult(BaseModel):
    """Execution-facing verdict; independent of the generation status."""

    verification_id: str
    finding_id: str
    condition: str
    outcome: Literal[
        "violation_present", "not_observed_within_scope", "execution_error",
        "inconclusive", "not_verifiable", "invalid_test",
    ]
    detail: str = ""
    assertion_message: str | None = None
    llm_assessment: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class ProbeManifestVerification(BaseModel):
    verification_id: str
    finding_id: str
    test_path: str
    test_name: str
    strategy: str
    covered_property: str
    target_components: list[str]
    generated_by: str | None = None
    generation_status: str = "generated"
    coverage_limitations: list[str] = Field(default_factory=list)
    condition: str = ""
    language: str = "python"
    framework: str = "pytest"
    evidence_refs: list[str] = Field(default_factory=list)
    source_commit: str = ""


class ProbeManifest(BaseModel):
    schema_version: str = MANIFEST_SCHEMA_VERSION
    generator: str = GENERATOR_ID
    generator_version: str = GENERATOR_VERSION
    audit_id: str
    source_commit: str
    suite_id: str
    runner: str = "uv"
    root_layout: str = ".tallercito"
    language: str = "python"
    framework: str = "pytest"
    verifications: list[ProbeManifestVerification] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ProbeRequest(BaseModel):
    findings_path: str
    repo_path: str | None = None
    architecture_context_path: str | None = None
    output_path: str
    audit_id: str | None = None
    green_control_dir: str | None = None
    execution_id: str | None = None


class ProbeResult(BaseModel):
    ok: bool
    termination_reason: str
    output_zip: str | None = None
    suite_id: str | None = None
    source_commit: str | None = None
    repository_id: str = ""
    total_findings: int = 0
    verifications: list[VerificationResult] = Field(default_factory=list)
    validation_records: list[ValidationRecord] = Field(default_factory=list)
    validation_status: str = "not_run"  # not_run|validated|partial|environment_blocked|invalid|not_applicable
    metrics: dict = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
