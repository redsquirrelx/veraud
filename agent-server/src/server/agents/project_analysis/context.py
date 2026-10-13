"""Per-run dependencies and snapshot-bound reference validation, in memory."""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from time import monotonic
from types import MappingProxyType

from pydantic import BaseModel

from ...services.repository_analysis import RepositoryQueryService, RepositorySnapshot
from .schemas import (
    ArchitectureAnalysisInput,
    BudgetUsage,
    InvestigationPlan,
    ProjectAnalysisInput,
    ProjectAnalysisReport,
    ProjectAnalysisRunResult,
    RetrievedEvidence,
)
from .state import ProjectAnalysisState


def walk_contracts(value: object) -> Iterator[BaseModel]:
    if isinstance(value, BaseModel):
        yield value
        for name in type(value).model_fields:
            yield from walk_contracts(getattr(value, name))
    elif isinstance(value, (tuple, list)):
        for item in value:
            yield from walk_contracts(item)


@dataclass(frozen=True)
class ProjectAnalysisContext:
    """Injected LangGraph runtime context, constructed once for each run.

    It owns no model clients, callbacks, filesystem handles, or persistent store.
    Model/client lifecycle stays with the caller in subsequent integration phases.
    The raw query service is an internal dependency, not an agent-facing tool;
    documentation policy is enforced by RepositoryToolset adapters.
    """

    snapshot: RepositorySnapshot = field(repr=False)
    input: ProjectAnalysisInput
    queries: RepositoryQueryService = field(init=False, repr=False)
    reference_indexes: Mapping[str, Mapping[str, BaseModel]] = field(
        init=False, repr=False
    )
    started_at: float = field(default_factory=monotonic, init=False)

    def __post_init__(self) -> None:
        self.require_snapshot(self.input.snapshot_hash)
        if self.input.snapshot_schema_version != self.snapshot.schema_version:
            raise ValueError("Unsupported or mismatched snapshot schema version.")
        indexes = {}
        collections = {
            "project": self.snapshot.projects,
            "file": self.snapshot.files,
            "directory": self.snapshot.directories,
            "symbol": self.snapshot.symbols,
            "technology": self.snapshot.technologies,
            "dependency": self.snapshot.dependencies,
            "relationship": self.snapshot.relationships,
            "architecture_signal": self.snapshot.architecture_signals,
            "entrypoint": self.snapshot.entrypoints,
            "infrastructure": self.snapshot.infrastructure,
            "test_configuration": self.snapshot.testing,
            "snapshot_evidence": self.snapshot.evidence,
        }
        for kind, records in collections.items():
            index = {record.id: record for record in records}
            if len(index) != len(records):
                raise ValueError(f"Duplicate snapshot {kind} identifiers.")
            indexes[kind] = MappingProxyType(index)
        object.__setattr__(self, "reference_indexes", MappingProxyType(indexes))
        object.__setattr__(self, "queries", RepositoryQueryService(self.snapshot))

    def require_snapshot(self, snapshot_hash: str) -> None:
        if snapshot_hash != self.snapshot.repository.snapshot_hash:
            raise ValueError("Analysis and repository snapshot hashes must match.")

    @property
    def elapsed_seconds(self) -> float:
        return monotonic() - self.started_at

    def initial_state(self) -> ProjectAnalysisState:
        return ProjectAnalysisState(
            input=self.input,
            snapshot_hash=self.input.snapshot_hash,
            repository_overview=self.queries.get_repository_overview(),
            candidates=(),
            planning_decisions=(),
            investigation_plan=None,
            offered_candidate_ids=(),
            plan_proposal=None,
            planning_status="pending",
            investigation_queue=(),
            active_investigation=None,
            investigation_messages=[],
            investigation_draft=None,
            investigation_turn=None,
            pending_tool_calls=(),
            investigation_model_calls=0,
            investigation_status="pending",
            investigation_evidence_ids=(),
            retrieved_evidence=(),
            findings=(),
            open_questions=(),
            execution_issues=(),
            budget_usage=BudgetUsage(),
            plan_corrections=0,
            finding_corrections=0,
            report_repairs=0,
            report_draft=None,
            report_selection=None,
            report_status="pending",
            validation_errors=(),
            completion_status=None,
            result=None,
        )

    def validate_plan(
        self, plan: InvestigationPlan, *, known_finding_ids: tuple[str, ...] = ()
    ) -> None:
        local = self._local_indexes(plan)
        self._validate_references(plan, local, set(known_finding_ids))
        if len(plan.objectives) > self.input.budget.max_investigations:
            raise ValueError("Plan exceeds the investigation budget.")
        for objective in plan.objectives:
            for seed in objective.seed_entity_ids:
                entity = self._snapshot_entity(seed)
                project_id = getattr(entity, "project_id", None)
                if seed in self.reference_indexes["project"]:
                    project_id = seed
                if project_id != objective.project_id:
                    raise ValueError(
                        "Investigation seeds must belong to the selected project."
                    )
        for decision in plan.decisions:
            if (
                decision.disposition in ("accepted", "grouped")
                and decision.investigation_id is None
            ):
                raise ValueError(
                    "Accepted/grouped decisions require an investigation reference."
                )

    def validate_report(self, report: ProjectAnalysisReport) -> None:
        """Validate identity and reference shape, not semantic evidence sufficiency."""
        self.require_snapshot(report.snapshot_hash)
        self.validate_plan(
            report.investigation_plan,
            known_finding_ids=tuple(
                outcome.id for outcome in report.investigation_outcomes
            ),
        )
        local = self._local_indexes(report)
        self._validate_references(report, local)
        for retrieval in report.retrieved_evidence:
            self._validate_retrieval(retrieval)

    def validate_result(self, result: ProjectAnalysisRunResult) -> None:
        for retrieval in result.retrieved_evidence:
            self._validate_retrieval(retrieval)
        if result.report is not None:
            self.validate_report(result.report)
            local = self._local_indexes((result.report, result.retrieved_evidence, *(
                getattr(finding, name) for finding in result.validated_findings
                for name in type(finding).model_fields if name != "id"
            )))
            self._validate_references(result, local)
        else:
            self._validate_references(result, self._local_indexes(result))

    def validate_architecture_input(self, handoff: ArchitectureAnalysisInput) -> None:
        self.require_snapshot(handoff.snapshot_hash)
        self.validate_report(handoff.project_analysis_report)
        self._validate_references(
            handoff, self._local_indexes(handoff.project_analysis_report)
        )

    def _snapshot_entity(self, identifier: str) -> BaseModel:
        for kind, index in self.reference_indexes.items():
            if kind != "snapshot_evidence" and identifier in index:
                return index[identifier]
        raise ValueError(f"Unknown snapshot entity reference: {identifier}")

    def _local_indexes(self, value: BaseModel) -> dict[str, dict[str, BaseModel]]:
        indexes: dict[str, dict[str, BaseModel]] = {}
        all_records = {}
        for record in walk_contracts(value):
            identifier = getattr(record, "id", None)
            if identifier is None:
                continue
            if any(identifier in index for index in self.reference_indexes.values()):
                raise ValueError(
                    f"Local identifier collides with snapshot entity: {identifier}"
                )
            if identifier in all_records and all_records[identifier] != record:
                raise ValueError(f"Conflicting local identifier: {identifier}")
            all_records[identifier] = record
            indexes.setdefault(type(record).__name__, {})[identifier] = record
        return indexes

    def _validate_references(
        self,
        value: BaseModel,
        local: dict[str, dict[str, BaseModel]],
        known_finding_ids: set[str] | None = None,
    ) -> None:
        snapshot_fields = {
            "project_id": "project",
            "project_ids": "project",
            "selected_project_ids": "project",
            "investigated_project_ids": "project",
            "file_id": "file",
            "file_ids": "file",
            "inspected_file_ids": "file",
            "symbol_ids": "symbol",
            "technology_ids": "technology",
            "entrypoint_id": "entrypoint",
            "entrypoint_ids": "entrypoint",
            "investigated_entrypoint_ids": "entrypoint",
            "dependency_ids": "dependency",
            "infrastructure_ids": "infrastructure",
            "test_configuration_ids": "test_configuration",
            "snapshot_evidence_ids": "snapshot_evidence",
        }
        local_fields = {
            "component_ids": "FunctionalComponent",
            "source_component_id": "FunctionalComponent",
            "target_component_id": "FunctionalComponent",
            "integration_ids": "IntegrationFinding",
            "candidate_id": "InvestigationCandidate",
        }
        coverage = getattr(value, "investigation_coverage", None)
        investigation_ids = set(local.get("InvestigationObjective", {}))
        if coverage is not None:
            investigation_ids.update(coverage.planned_investigation_ids)
        for record in walk_contracts(value):
            for name in type(record).model_fields:
                content = getattr(record, name)
                if content is None:
                    continue
                references = content if isinstance(content, tuple) else (content,)
                if name in snapshot_fields:
                    allowed = self.reference_indexes[snapshot_fields[name]]
                elif name in local_fields:
                    allowed = local.get(local_fields[name], {})
                elif name in ("entity_ids", "seed_entity_ids"):
                    for reference in references:
                        if name == "seed_entity_ids" or not any(
                            reference in index for index in local.values()
                        ):
                            self._snapshot_entity(reference)
                    continue
                elif name == "evidence_ids":
                    allowed = set(self.reference_indexes["snapshot_evidence"]) | set(
                        local.get("RetrievedEvidence", {})
                    )
                elif name == "origin_finding_ids":
                    allowed = known_finding_ids or (
                        set(local.get("InvestigationResult", {}))
                        | set(local.get("InvestigationOutcome", {}))
                    )
                elif name in ("investigation_id", "blocked_investigation_ids"):
                    # Deferred/rejected decisions may refer to no scheduled objective.
                    allowed = investigation_ids
                else:
                    continue
                for reference in references:
                    if reference not in allowed:
                        raise ValueError(f"Unknown {name} reference: {reference}")

    def _validate_retrieval(self, retrieval: RetrievedEvidence) -> None:
        self.require_snapshot(retrieval.snapshot_hash)
        source_file = self.reference_indexes["file"][retrieval.file_id]
        if source_file.content_hash != retrieval.content_hash:
            raise ValueError("Retrieval content hash does not match retained source.")
        if retrieval.start_line is not None and retrieval.end_line > (
            source_file.line_count or 0
        ):
            raise ValueError("Retrieval line range is outside retained source.")
        for identifier in retrieval.snapshot_evidence_ids:
            evidence = self.reference_indexes["snapshot_evidence"][identifier]
            if evidence.file_id != retrieval.file_id:
                raise ValueError(
                    "Retrieval and snapshot evidence must refer to the same file."
                )
