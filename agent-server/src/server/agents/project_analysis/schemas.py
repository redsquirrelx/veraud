"""Typed contracts for evidence-backed project investigation and handoff."""

from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .telemetry import ExecutionTelemetry

Identifier = Annotated[str, Field(min_length=1)]
Text = Annotated[str, Field(min_length=1)]
SnapshotHash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
CompletionStatus = Literal["complete", "partial", "failed"]
ClaimStatus = Literal["supported", "hypothesis", "unresolved"]
PriorityTier = Literal[
    "project_orientation",
    "startup",
    "representative_flow",
    "shared_component_or_integration",
    "material_uncertainty",
]
ReportSection = Literal[
    "project_identification",
    "functional_components",
    "main_flows",
    "component_relationships",
    "integrations_and_state",
    "testing",
]


class AnalysisContract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    @model_validator(mode="after")
    def validate_unique_collection_members(self) -> Self:
        for name in type(self).model_fields:
            value = getattr(self, name)
            if not isinstance(value, tuple):
                continue
            identifiers = [getattr(item, "id", item) for item in value]
            if len(set(identifiers)) != len(identifiers):
                raise ValueError(f"Duplicate members in {name}.")
        return self


class InvestigationBudget(AnalysisContract):
    max_investigations: int = Field(default=12, ge=1)
    max_model_calls: int = Field(default=40, ge=1)
    reserved_report_model_calls: int = Field(default=0, ge=0)
    max_total_tokens: int = Field(default=60_000, ge=1000)
    max_input_tokens_per_call: int = Field(default=6000, ge=500)
    max_tokens_per_investigation: int = Field(default=20_000, ge=1000)
    max_output_tokens_per_call: int = Field(default=3000, ge=256)
    max_tool_calls: int = Field(default=100, ge=1)
    max_retrieved_characters: int = Field(default=150_000, ge=1)
    max_elapsed_seconds: float = Field(default=600, gt=0, allow_inf_nan=False)
    max_plan_corrections: int = Field(default=1, ge=0)
    max_finding_corrections: int = Field(default=1, ge=0)
    max_report_repairs: int = Field(default=2, ge=0)

    @model_validator(mode="after")
    def validate_reserve(self) -> Self:
        if self.reserved_report_model_calls >= self.max_model_calls:
            raise ValueError(
                "Report reserve must leave at least one investigation model call."
            )
        return self


class BudgetUsage(AnalysisContract):
    investigations_started: int = Field(default=0, ge=0)
    model_calls: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    retrieved_characters: int = Field(default=0, ge=0)
    elapsed_seconds: float = Field(default=0, ge=0, allow_inf_nan=False)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    reported_input_tokens: int = Field(default=0, ge=0)
    reported_output_tokens: int = Field(default=0, ge=0)
    unknown_usage_attempts: int = Field(default=0, ge=0)
    provider_attempts: int = Field(default=0, ge=0)
    provider_retries: int = Field(default=0, ge=0)
    provider_wait_seconds: float = Field(default=0, ge=0)
    accounted_tokens: int = Field(default=0, ge=0)
    estimated_tokens: int = Field(default=0, ge=0)
    token_budget_exhausted: bool = False


class ProjectAnalysisInput(AnalysisContract):
    snapshot_hash: SnapshotHash
    snapshot_schema_version: Literal["1"] = "1"
    budget: InvestigationBudget = Field(default_factory=InvestigationBudget)


class InvestigationCandidate(AnalysisContract):
    id: Identifier
    project_id: Identifier
    category: PriorityTier
    seed_entity_ids: tuple[Identifier, ...] = Field(min_length=1)
    description: Text
    limitations: tuple[Text, ...] = ()


class InvestigationObjective(AnalysisContract):
    id: Identifier
    project_id: Identifier
    objective: Text
    seed_entity_ids: tuple[Identifier, ...] = Field(min_length=1)
    questions: tuple[Text, ...] = Field(min_length=1)
    report_sections: tuple[ReportSection, ...] = Field(min_length=1)
    selection_reason: Text
    priority_tier: PriorityTier
    expected_deliverable: Text
    completion_criteria: tuple[Text, ...] = Field(min_length=1)
    origin_finding_ids: tuple[Identifier, ...] = ()
    blocked_investigation_ids: tuple[Identifier, ...] = ()
    estimated_effort: Literal["low", "medium", "high"] = "medium"


class ProposedInvestigation(AnalysisContract):
    objective: InvestigationObjective
    candidate_ids: tuple[Identifier, ...] = Field(min_length=1)


class CandidateOmission(AnalysisContract):
    id: Identifier
    candidate_id: Identifier
    disposition: Literal["deferred", "rejected"]
    reason: Text


class InvestigationProposal(AnalysisContract):
    investigations: tuple[ProposedInvestigation, ...] = ()
    omissions: tuple[CandidateOmission, ...] = ()


class PlanningDecision(AnalysisContract):
    id: Identifier
    candidate_id: Identifier
    disposition: Literal["accepted", "grouped", "deferred", "rejected"]
    reason: Text
    investigation_id: Identifier | None = None


class InvestigationPlan(AnalysisContract):
    candidates: tuple[InvestigationCandidate, ...] = ()
    objectives: tuple[InvestigationObjective, ...] = ()
    decisions: tuple[PlanningDecision, ...] = ()


class RetrievedEvidence(AnalysisContract):
    """Retrieval provenance, without duplicating source content in graph state."""

    id: Identifier
    snapshot_hash: SnapshotHash
    file_id: Identifier
    content_hash: SnapshotHash
    tool_call_id: Identifier
    kind: Literal["source", "metadata"]
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    snapshot_evidence_ids: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if (self.start_line is None) != (self.end_line is None):
            raise ValueError("Source ranges require both start_line and end_line.")
        if self.kind == "source" and self.start_line is None:
            raise ValueError("Source retrieval requires a line range.")
        if self.start_line is not None and self.end_line < self.start_line:
            raise ValueError("end_line must not precede start_line.")
        return self


class AnalysisClaim(AnalysisContract):
    id: Identifier
    statement: Text
    status: ClaimStatus
    entity_ids: tuple[Identifier, ...] = ()
    evidence_ids: tuple[Identifier, ...] = ()
    limitations: tuple[Text, ...] = ()

    @model_validator(mode="after")
    def validate_support(self) -> Self:
        if self.status == "supported" and not self.evidence_ids:
            raise ValueError("Supported claims require evidence.")
        if self.status != "supported" and not self.limitations:
            raise ValueError(
                "Hypothesis and unresolved claims require explicit limitations."
            )
        return self


class ProjectIdentification(AnalysisContract):
    id: Identifier
    project_id: Identifier
    name: Text
    application_types: tuple[
        Literal[
            "api",
            "cli",
            "library",
            "web_application",
            "desktop_application",
            "game",
            "worker",
            "data_pipeline",
            "script",
            "tooling",
            "example",
            "unknown",
        ],
        ...,
    ] = Field(min_length=1)
    purpose: AnalysisClaim
    technology_ids: tuple[Identifier, ...] = ()
    entrypoint_ids: tuple[Identifier, ...] = ()


class FunctionalComponent(AnalysisContract):
    id: Identifier
    name: Text
    project_id: Identifier
    responsibility: AnalysisClaim
    file_ids: tuple[Identifier, ...] = ()
    symbol_ids: tuple[Identifier, ...] = ()
    entrypoint_ids: tuple[Identifier, ...] = ()
    dependency_ids: tuple[Identifier, ...] = ()


class OpenQuestion(AnalysisContract):
    id: Identifier
    question: Text
    reason: Text
    entity_ids: tuple[Identifier, ...] = ()
    investigation_id: Identifier | None = None


class FlowStep(AnalysisContract):
    id: Identifier
    description: AnalysisClaim
    component_ids: tuple[Identifier, ...] = ()
    symbol_ids: tuple[Identifier, ...] = ()


class FunctionalFlow(AnalysisContract):
    id: Identifier
    name: Text
    project_id: Identifier
    trigger: AnalysisClaim
    entrypoint_id: Identifier | None = None
    steps: tuple[FlowStep, ...] = Field(min_length=1)
    integration_ids: tuple[Identifier, ...] = ()
    unresolved_steps: tuple[OpenQuestion, ...] = ()


class ComponentRelationship(AnalysisContract):
    id: Identifier
    source_component_id: Identifier
    target_component_id: Identifier
    kind: Literal[
        "imports",
        "calls",
        "implements",
        "reads_from",
        "writes_to",
        "invokes_external_service",
    ]
    description: AnalysisClaim


class IntegrationFinding(AnalysisContract):
    id: Identifier
    project_id: Identifier
    name: Text
    kind: Literal[
        "database", "storage", "queue", "external_service", "in_memory_state", "other"
    ]
    usage: Literal["declared", "verified", "unresolved"]
    state_kind: Literal["persistent", "in_memory", "stateless", "unknown"] = "unknown"
    description: AnalysisClaim
    component_ids: tuple[Identifier, ...] = ()
    infrastructure_ids: tuple[Identifier, ...] = ()
    dependency_ids: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def validate_verified_usage(self) -> Self:
        if self.usage == "verified" and self.description.status != "supported":
            raise ValueError("Verified integration usage requires a supported claim.")
        return self


class TestingFinding(AnalysisContract):
    id: Identifier
    project_id: Identifier
    test_configuration_ids: tuple[Identifier, ...] = ()
    inspected_file_ids: tuple[Identifier, ...] = ()
    observations: tuple[AnalysisClaim, ...] = ()


class InvestigationResult(AnalysisContract):
    id: Identifier
    investigation_id: Identifier
    status: Literal["completed", "incomplete"]
    project_identification: tuple[ProjectIdentification, ...] = ()
    components: tuple[FunctionalComponent, ...] = ()
    flows: tuple[FunctionalFlow, ...] = ()
    component_relationships: tuple[ComponentRelationship, ...] = ()
    integrations: tuple[IntegrationFinding, ...] = ()
    claims: tuple[AnalysisClaim, ...] = ()
    testing: tuple[TestingFinding, ...] = ()
    open_questions: tuple[OpenQuestion, ...] = ()
    suggested_followups: tuple[InvestigationObjective, ...] = ()
    limitations: tuple[Text, ...] = ()

    @model_validator(mode="after")
    def validate_incomplete(self) -> Self:
        if self.status == "incomplete" and not (
            self.limitations or self.open_questions
        ):
            raise ValueError(
                "Incomplete investigations require a reason or open question."
            )
        return self


class RepositoryToolCall(AnalysisContract):
    id: Identifier
    name: Text
    arguments: dict[str, Any] = Field(default_factory=dict)


class FollowupRequest(AnalysisContract):
    question: Text
    seed_entity_ids: tuple[Identifier, ...] = Field(min_length=1)
    blocked_investigation_ids: tuple[Identifier, ...] = ()


class InvestigationTurn(AnalysisContract):
    tool_calls: tuple[RepositoryToolCall, ...] = ()
    result: InvestigationResult | None = None
    followups: tuple[FollowupRequest, ...] = ()

    @model_validator(mode="after")
    def validate_action(self) -> Self:
        if self.followups and self.result is None:
            raise ValueError("Followups must accompany an investigation result.")
        if bool(self.tool_calls) == (self.result is not None):
            raise ValueError("Return either tool calls or an investigation result.")
        return self


class ReportSelection(AnalysisContract):
    """Order accepted facts without inventing or silently discarding conclusions."""

    project_identification: tuple[Identifier, ...] = ()
    functional_components: tuple[Identifier, ...] = ()
    main_flows: tuple[Identifier, ...] = ()
    component_relationships: tuple[Identifier, ...] = ()
    integrations_and_state: tuple[Identifier, ...] = ()
    testing: tuple[Identifier, ...] = ()
    claims: tuple[Identifier, ...] = ()
    open_questions: tuple[Identifier, ...] = ()


class InvestigationCoverage(AnalysisContract):
    selected_project_ids: tuple[Identifier, ...] = ()
    investigated_project_ids: tuple[Identifier, ...] = ()
    inspected_file_ids: tuple[Identifier, ...] = ()
    investigated_entrypoint_ids: tuple[Identifier, ...] = ()
    planned_investigation_ids: tuple[Identifier, ...] = ()
    completed_investigation_ids: tuple[Identifier, ...] = ()
    incomplete_investigation_ids: tuple[Identifier, ...] = ()
    pending_investigation_ids: tuple[Identifier, ...] = ()
    deferred_decisions: tuple[PlanningDecision, ...] = ()
    limitations: tuple[Text, ...] = ()

    @model_validator(mode="after")
    def validate_partition(self) -> Self:
        groups = [
            set(self.completed_investigation_ids),
            set(self.incomplete_investigation_ids),
            set(self.pending_investigation_ids),
        ]
        if any(
            groups[left] & groups[right]
            for left in range(3)
            for right in range(left + 1, 3)
        ):
            raise ValueError("Investigation completion groups must be disjoint.")
        if set.union(*groups) != set(self.planned_investigation_ids):
            raise ValueError(
                "Every planned investigation must have exactly one coverage status."
            )
        if not set(self.investigated_project_ids) <= set(self.selected_project_ids):
            raise ValueError("Investigated projects must be selected projects.")
        return self


class ExecutionIssue(AnalysisContract):
    id: Identifier
    stage: Text
    category: Text
    message: Text
    investigation_id: Identifier | None = None


class InvestigationOutcome(AnalysisContract):
    """Compact provenance ledger; id matches the accepted InvestigationResult id."""

    id: Identifier
    investigation_id: Identifier
    status: Literal["completed", "incomplete"]
    limitations: tuple[Text, ...] = ()


class ProjectAnalysisReport(AnalysisContract):
    schema_version: Literal["1"] = "1"
    snapshot_hash: SnapshotHash
    investigation_plan: InvestigationPlan
    investigation_outcomes: tuple[InvestigationOutcome, ...] = ()
    project_identification: tuple[ProjectIdentification, ...] = ()
    functional_components: tuple[FunctionalComponent, ...] = ()
    main_flows: tuple[FunctionalFlow, ...] = ()
    component_relationships: tuple[ComponentRelationship, ...] = ()
    integrations_and_state: tuple[IntegrationFinding, ...] = ()
    testing: tuple[TestingFinding, ...] = ()
    claims: tuple[AnalysisClaim, ...] = ()
    retrieved_evidence: tuple[RetrievedEvidence, ...] = ()
    open_questions: tuple[OpenQuestion, ...] = ()
    investigation_coverage: InvestigationCoverage

    @model_validator(mode="after")
    def validate_plan_coverage(self) -> Self:
        planned_ids = {objective.id for objective in self.investigation_plan.objectives}
        if planned_ids != set(self.investigation_coverage.planned_investigation_ids):
            raise ValueError(
                "Report coverage must match the accepted investigation plan."
            )
        coverage = self.investigation_coverage
        for status, expected in (
            ("completed", coverage.completed_investigation_ids),
            ("incomplete", coverage.incomplete_investigation_ids),
        ):
            actual = [
                outcome.investigation_id
                for outcome in self.investigation_outcomes
                if outcome.status == status
            ]
            if len(actual) != len(set(actual)) or set(actual) != set(expected):
                raise ValueError("Investigation outcomes must match report coverage.")
        return self


class ProjectAnalysisRunResult(AnalysisContract):
    completion_status: CompletionStatus
    telemetry: ExecutionTelemetry = Field(default_factory=ExecutionTelemetry)
    investigation_plan: InvestigationPlan | None = None
    validated_findings: tuple[InvestigationResult, ...] = ()
    retrieved_evidence: tuple[RetrievedEvidence, ...] = ()
    report: ProjectAnalysisReport | None = None
    investigation_coverage: InvestigationCoverage
    unresolved_questions: tuple[OpenQuestion, ...] = ()
    execution_issues: tuple[ExecutionIssue, ...] = ()
    usage: BudgetUsage = Field(default_factory=BudgetUsage)

    @model_validator(mode="after")
    def validate_completion(self) -> Self:
        if self.completion_status == "failed":
            if self.report is not None or not self.execution_issues:
                raise ValueError(
                    "Failed runs require execution issues and no valid report."
                )
        elif self.report is None:
            raise ValueError("Complete and partial runs require a report.")
        if self.report is not None:
            if (
                self.investigation_plan is not None
                and self.investigation_plan != self.report.investigation_plan
            ):
                raise ValueError("Run and report investigation plans must match.")
            if self.report.investigation_coverage != self.investigation_coverage:
                raise ValueError("Run and report coverage must match.")
            if self.report.open_questions != self.unresolved_questions:
                raise ValueError("Run and report unresolved questions must match.")
        coverage = self.investigation_coverage
        if self.investigation_plan is not None and {
            objective.id for objective in self.investigation_plan.objectives
        } != set(coverage.planned_investigation_ids):
            raise ValueError("Run plan and investigation coverage must match.")
        if self.completion_status == "complete" and (
            not coverage.planned_investigation_ids
            or coverage.pending_investigation_ids
            or coverage.incomplete_investigation_ids
        ):
            raise ValueError(
                "Complete runs require a nonempty, completed investigation plan."
            )
        if self.completion_status == "partial" and not (
            coverage.pending_investigation_ids
            or coverage.incomplete_investigation_ids
            or coverage.limitations
            or self.execution_issues
        ):
            raise ValueError(
                "Partial runs require an explicit incomplete scope or execution reason."
            )
        return self


class ArchitectureBrief(AnalysisContract):
    """Functional facts and cited provenance, without candidate audits or history."""

    snapshot_hash: SnapshotHash
    investigation_objectives: tuple[InvestigationObjective, ...] = ()
    deferred_candidate_counts: tuple[tuple[str, int], ...] = ()
    project_identification: tuple[ProjectIdentification, ...] = ()
    functional_components: tuple[FunctionalComponent, ...] = ()
    main_flows: tuple[FunctionalFlow, ...] = ()
    component_relationships: tuple[ComponentRelationship, ...] = ()
    integrations_and_state: tuple[IntegrationFinding, ...] = ()
    testing: tuple[TestingFinding, ...] = ()
    claims: tuple[AnalysisClaim, ...] = ()
    open_questions: tuple[OpenQuestion, ...] = ()
    retrieved_evidence: tuple[RetrievedEvidence, ...] = ()
    investigation_outcomes: tuple[InvestigationOutcome, ...] = ()
    investigation_coverage: InvestigationCoverage
    completion_status: Literal["complete", "partial"]
    execution_issues: tuple[ExecutionIssue, ...] = ()

    @classmethod
    def from_result(cls, result):
        if result.report is None:
            raise ValueError("A failed run cannot supply an architecture brief.")
        from collections import Counter

        from .context import walk_contracts

        report = result.report
        fields = {
            name: getattr(report, name)
            for name in (
                "project_identification",
                "functional_components",
                "main_flows",
                "component_relationships",
                "integrations_and_state",
                "testing",
                "claims",
                "open_questions",
            )
        }
        citations = {
            identifier
            for record in walk_contracts(tuple(fields.values()))
            for identifier in getattr(record, "evidence_ids", ())
        }
        cited_files = {
            record.file_id
            for record in report.retrieved_evidence
            if record.id in citations or set(record.snapshot_evidence_ids) & citations
        }
        selected = tuple(
            record
            for record in report.retrieved_evidence
            if record.id in citations
            or set(record.snapshot_evidence_ids) & citations
            or (record.kind == "source" and record.file_id in cited_files)
        )
        return cls(
            snapshot_hash=report.snapshot_hash,
            investigation_objectives=report.investigation_plan.objectives,
            deferred_candidate_counts=tuple(
                sorted(
                    Counter(
                        candidate.category
                        for candidate in report.investigation_plan.candidates
                        if candidate.id
                        in {
                            decision.candidate_id
                            for decision in report.investigation_coverage.deferred_decisions
                        }
                    ).items()
                )
            ),
            completion_status=result.completion_status,
            retrieved_evidence=selected,
            investigation_coverage=report.investigation_coverage.model_copy(
                update={"deferred_decisions": ()}
            ),
            investigation_outcomes=report.investigation_outcomes,
            execution_issues=result.execution_issues,
            **fields,
        )


class ArchitectureAnalysisInput(AnalysisContract):
    snapshot_hash: SnapshotHash
    project_analysis_report: ProjectAnalysisReport
    investigation_coverage: InvestigationCoverage
    unresolved_questions: tuple[OpenQuestion, ...] = ()
    execution_issues: tuple[ExecutionIssue, ...] = ()

    @model_validator(mode="after")
    def validate_report_binding(self) -> Self:
        report = self.project_analysis_report
        if self.snapshot_hash != report.snapshot_hash:
            raise ValueError(
                "Architecture input and report snapshot hashes must match."
            )
        if self.investigation_coverage != report.investigation_coverage:
            raise ValueError("Architecture input and report coverage must match.")
        if self.unresolved_questions != report.open_questions:
            raise ValueError("Architecture input and report questions must match.")
        return self

    @classmethod
    def from_result(cls, result: ProjectAnalysisRunResult) -> Self:
        if result.report is None:
            raise ValueError("Failed analysis cannot be handed off as a valid report.")
        return cls(
            snapshot_hash=result.report.snapshot_hash,
            project_analysis_report=result.report,
            investigation_coverage=result.investigation_coverage,
            unresolved_questions=result.unresolved_questions,
            execution_issues=result.execution_issues,
        )
