"""Explicit output-to-knowledge mapping shared by investigator and hierarchy runtimes."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel

from ..services.execution_failures import ExecutionValidationError
from .identity import AuditIdentity
from .interface import Blackboard
from .models import Assessment, BlackboardRecord, Evidence, Finding


def _append[RecordT: BlackboardRecord](
    record: RecordT, read: Callable[[str, str], RecordT | None], publish: Callable[[RecordT], str],
) -> str:
    # Reconstructed sessions must replay the original timestamp, not manufacture
    # a conflicting new record solely because publication is being retried.
    existing = read(record.run_id, record.id)
    if existing is not None:
        record = record.model_copy(update={"created_at": existing.created_at})
        _check_conflict(record, existing)
    try:
        return publish(record)
    except ValueError:
        if existing is not None:
            raise
        # Another publisher may have inserted between our read and append.
        # Only an identical record (apart from its generated timestamp) is a retry.
        stored = read(record.run_id, record.id)
        if stored is None:
            raise
        _check_conflict(record.model_copy(update={"created_at": stored.created_at}), stored)
        return stored.id


def _check_conflict(record: BlackboardRecord, existing: BlackboardRecord) -> None:
    fields = sorted(key for key in type(record).model_fields if getattr(record, key) != getattr(existing, key))
    if fields:
        raise ExecutionValidationError("blackboard_publication_conflict",
            "La publicación entra en conflicto con un registro original del blackboard; se conserva el original.",
            stage="publish_result", diagnostics=[f"record_type={type(record).__name__}", "differing_fields=" + ",".join(fields)])


@dataclass(frozen=True)
class PublishedResult:
    finding_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    assessment_ids: tuple[str, ...] = ()


class Publication:
    """One invocation within a shared audit; children keep their assigned identities.

    Retain completed publications so supervisors reference the original claims,
    even if collection later rejects or withdraws them. A standalone run creates
    a fresh session; the agent itself does not retain a previous run's session.
    """

    def __init__(self, blackboard: Blackboard, agent_id: str, *, run_id: str | None = None,
                 invocation_id: str | None = None, identity: AuditIdentity | None = None):
        if identity is not None and (run_id is not None or invocation_id is not None):
            raise ValueError("Supply an audit identity or individual IDs, not both.")
        self.blackboard = blackboard
        self.agent_id = agent_id
        self.identity = identity if identity is not None else AuditIdentity(**{
            name: value for name, value in {"run_id": run_id, "invocation_id": invocation_id}.items()
            if value is not None
        })
        self.created_at = datetime.now(UTC)
        self._children: dict[str, Publication] = {}
        self.result: PublishedResult | None = None

    @property
    def run_id(self) -> str:
        return self.identity.run_id

    @property
    def invocation_id(self) -> str:
        return self.identity.invocation_id

    def child(self, invocation_id: str, agent_id: str) -> "Publication":
        if invocation_id not in self._children:
            self._children[invocation_id] = Publication(
                self.blackboard, agent_id, identity=self.identity.child(invocation_id),
            )
        child = self._children[invocation_id]
        if child.agent_id != agent_id:
            raise ValueError("Publication invocation belongs to another agent.")
        return child

    def record_id(self, entity: str, local_id: str) -> str:
        # A coordinator/manager has one final assessment per invocation, even if
        # a retry presents a different report-local assessment ID.
        if entity == "assessment":
            local_id = ""
        return str(uuid5(NAMESPACE_URL, json.dumps([self.run_id, self.invocation_id, entity, local_id])))

    def _identity(self, entity: str, local_id: str) -> dict:
        return {"id": self.record_id(entity, local_id), "run_id": self.run_id,
                "invocation_id": self.invocation_id, "agent_id": self.agent_id,
                "local_id": local_id, "created_at": self.created_at}

    def publish_investigation(self, result: BaseModel, references, *, tool_measurements=()) -> PublishedResult:
        report = result.model_dump(mode="json", serialize_as_any=True)
        investigation = {key: value for key, value in report.items() if key != "findings"}
        measurements = {item.call_id: item.model_dump(mode="json") for item in tool_measurements}
        originals = {}
        for ref in [*references, *(ref for finding in report["findings"] for ref in finding["evidence"])]:
            value = ref.model_dump(mode="json") if isinstance(ref, BaseModel) else ref
            if value["id"] in originals and originals[value["id"]] != value:
                fields = sorted(key for key in set(Evidence.model_fields) | {"path"}
                    if originals[value["id"]].get(key) != value.get(key))
                raise ExecutionValidationError("blackboard_publication_conflict",
                    "La invocación contiene referencias incompatibles para una misma evidencia.", stage="publish_result",
                    diagnostics=["record_type=Evidence", "differing_fields=" + ",".join(fields)])
            originals[value["id"]] = value
        evidence = [Evidence(
            **self._identity("evidence", local_id),
            **{key: value for key, value in ref.items() if key not in {"id", "path"}},
            source=ref["path"], details={"reference": ref, "investigation": investigation,
                **({"tool_name": measurements[ref["tool_call_id"]]["tool"],
                    "measurement": measurements[ref["tool_call_id"]]} if ref["tool_call_id"] in measurements else {})},
        ) for local_id, ref in originals.items()]
        fields = {"title", "description", "kind", "criterion_id", "criterion", "components",
                  "justification", "modularity_impact", "severity", "confidence", "recommendation"}
        findings = [Finding(
            **self._identity("finding", finding["id"]),
            **{key: value for key, value in finding.items() if key in fields},
            evidence_ids=tuple(self.record_id("evidence", identifier) for identifier in dict.fromkeys(
                [*finding["evidence_ids"], *(ref["id"] for ref in finding["evidence"])])),
            # Investigator-local assessment IDs are not hierarchy Assessment IDs.
            details={**finding, "investigation": investigation},
        ) for finding in report["findings"]]
        # Validate the complete mapping before beginning append-only publication.
        for record in evidence:
            _append(record, self.blackboard.get_evidence, self.blackboard.publish_evidence)
        for record in findings:
            _append(record, self.blackboard.get_finding, self.blackboard.publish_finding)
        self.result = PublishedResult(tuple(r.id for r in findings), tuple(r.id for r in evidence))
        return self.result

    def publish_assessment(self, result: BaseModel) -> PublishedResult:
        children = []
        existing = self.blackboard.get_assessment(self.run_id, self.record_id("assessment", ""))
        if existing is not None:
            # Replaying a saved assessment must keep its original references,
            # not republish the supervisor's reviewed copies as original claims.
            children.append(PublishedResult(existing.finding_ids, existing.evidence_ids, existing.assessment_ids))
        else:
            manager = hasattr(result, "assessments")
            for invocation in result.assessments if manager else result.invocations:
                child = self.child(invocation.assignment.invocation_id, invocation.assignment.investigator_id)
                # Factory-provided agents may not run the common lifecycle. Their
                # validated outputs can still be retained by the collecting parent.
                if child.result is None and invocation.result is not None:
                    if manager:
                        child.publish_assessment(invocation.result)
                    else:
                        child.publish_investigation(invocation.result, invocation.evidence)
                if child.result is not None:
                    children.append(child.result)
        report = result.model_dump(mode="json", serialize_as_any=True)
        scope = report.get("scope", "")
        findings = tuple(dict.fromkeys(identifier for child in children for identifier in child.finding_ids))
        evidence = tuple(dict.fromkeys(identifier for child in children for identifier in child.evidence_ids))
        assessments = tuple(dict.fromkeys(identifier for child in children for identifier in child.assessment_ids))
        record = Assessment(
            **self._identity("assessment", report["assessment_id"]),
            **{key: report[key] for key in ("repository_id", "commit", "snapshot_hash", "objective", "targets",
                "status", "termination_reason", "summary", "limitations", "consumption", "rounds_completed", "duration_seconds")},
            quality_attribute=report.get("quality_attribute"), scope=scope,
            finding_ids=findings, evidence_ids=evidence, assessment_ids=assessments,
            consolidated_findings=report.get("consolidated_findings", []),
            coverage=report.get("coverage", {}), gaps=report.get("unresolved_gaps", report.get("material_gaps", [])),
            resolved_gap_ids=report.get("resolved_gap_ids", []),
            withdrawn_finding_refs=report.get("withdrawn_finding_refs", []),
            conclusions=report.get("conclusions", []),
            relationships=report.get("links", report.get("finding_relationships", [])),
            details={"report": report},
        )
        _append(record, self.blackboard.get_assessment, self.blackboard.publish_assessment)
        self.result = PublishedResult(findings, evidence, (record.id,))
        return self.result


def publication_for(agent) -> Publication | None:
    if agent.blackboard is None:
        return None
    bound = getattr(agent, "_blackboard_publication", None)
    if bound is not None:
        if bound.blackboard is not agent.blackboard:
            raise ValueError("Publication context belongs to another blackboard.")
        return bound
    return Publication(agent.blackboard, agent.agent_type, identity=getattr(agent, "audit_identity", None))


def publish_audit_context(blackboard: Blackboard, identity: AuditIdentity, snapshot, request, *, started_at: datetime) -> str:
    """Retain repository-analysis facts for blackboard-only report consumers.

    This is metadata, not source proof or an inferred architectural conclusion.
    No credentials, retained file contents or model configuration are published.
    """
    context = {
        "repository_id": snapshot.repository.name, "repository_location": snapshot.repository.root_path,
        "objective": request.objective, "targets": request.targets,
        "execution_started_at": started_at.isoformat(), "manager_invocation_id": identity.invocation_id,
        "languages": sorted({item.language for item in snapshot.files if item.status == "processed"}),
        "technologies": [item.model_dump(mode="json") for item in snapshot.technologies],
        "repository_structure": sorted({item.path.split("/")[0] for item in snapshot.files}),
        "modules": [item.path for item in snapshot.projects],
        "dependencies": [item.model_dump(mode="json") for item in snapshot.dependencies],
        "runtime_environment": [item.model_dump(mode="json") for item in snapshot.infrastructure],
        "limitations": list(snapshot.coverage.limitations),
        "exclusions": ["Documentación narrativa excluida del acceso de herramientas de auditoría."]}
    publication = Publication(blackboard, "repository_analysis", identity=identity)
    record = Evidence(**publication._identity("evidence", "audit-context"), kind="metadata",
        source="repository-analysis:context", snapshot_hash=snapshot.repository.snapshot_hash,
        commit=snapshot.repository.commit, file_id="repository:" + snapshot.repository.snapshot_hash,
        content_hash=snapshot.repository.snapshot_hash, tool_call_id="repository-analysis",
        details={"audit_context": context, "tool_name": "RepositoryAnalysisService"})
    return _append(record, blackboard.get_evidence, blackboard.publish_evidence)


def publish_audit_outcome(blackboard: Blackboard, identity: AuditIdentity, status: str) -> None:
    """Record terminal execution status for consumers that only read the blackboard."""
    publication = Publication(blackboard, "audit_execution", identity=identity)
    context = blackboard.get_evidence(identity.run_id, publication.record_id("evidence", "audit-context"))
    if context is None:
        return
    record = Evidence(**publication._identity("evidence", "audit-outcome:" + status), kind="metadata",
        source="audit-execution:outcome", snapshot_hash=context.snapshot_hash, commit=context.commit,
        file_id=context.file_id, content_hash=context.content_hash, tool_call_id="audit-execution",
        details={"audit_outcome": {"status": status}})
    _append(record, blackboard.get_evidence, blackboard.publish_evidence)
