"""Exact finding identity and shared anchors; no technical re-evaluation."""

import json
from itertools import combinations
from time import monotonic
from typing import Any

from pydantic import TypeAdapter

from server.runtimes.coordination.synthesis import evidence_key, stable_id

from .schemas import (
    ConsolidatedFinding,
    FindingContribution,
    FindingRelation,
    ReusabilityCoverage,
    ReusabilityResult,
)


def finalize_assessment(execution, state):
    records = state.get("investigation_results", [])
    groups, evidence, gaps, evaluated = {}, {}, [], []
    for record in records:
        result = record.result
        if result is not None:
            raw = TypeAdapter(Any).dump_python(result, mode="json")
            if record.status in {"completed", "partial"} and raw.get("plan") is not None and any(ref.kind == "source" for ref in record.evidence):
                evaluated.append(record.assignment.invocation_id)
            for ref in record.evidence:
                evidence.setdefault(stable_id("evidence", evidence_key(ref)), ref)
            for finding in raw["findings"]:
                identity = json.dumps({key: value for key, value in finding.items() if key != "id"}, sort_keys=True)
                groups.setdefault(identity, []).append((record, finding))
        if record.status != "completed":
            gaps.append({"kind": "incomplete_investigation", "invocation_id": record.assignment.invocation_id,
                "investigator_id": record.assignment.investigator_id, "status": record.status,
                "failure": record.failure.model_dump(mode="json") if record.failure else None})
    findings = []
    for identity, members in sorted(groups.items()):
        members.sort(key=lambda pair: (pair[0].assignment.invocation_id, pair[1]["id"]))
        first = members[0][1]
        citations = {ref.model_dump_json(): ref for row, finding in members for ref in row.evidence
            if ref.id in finding["evidence_ids"]}
        document_claim_ids = sorted({claim_id for _, finding in members
            for claim_id in finding.get("document_claim_ids", []) if isinstance(claim_id, str)})
        findings.append(ConsolidatedFinding(id=stable_id("reusability-finding", identity), concern=first["title"],
            affected_components=first["components"], severity=first["severity"], confidence=first["confidence"],
            evidence=[citations[key] for key in sorted(citations)],
            contributions=[FindingContribution(reference=f"{row.assignment.invocation_id}/{finding['id']}",
                invocation_id=row.assignment.invocation_id, investigator_id=row.assignment.investigator_id, finding=finding)
                for row, finding in members], limitations=list(dict.fromkeys(warning for row, _ in members for warning in row.warnings)),
            document_claim_ids=document_claim_ids))
    links = []
    known = {value for file in execution.tools.accessible_snapshot.files for value in (file.id, file.path)}
    known.update(symbol.id for symbol in execution.tools.accessible_snapshot.symbols)
    for left, right in combinations(findings, 2):
        if len({c.investigator_id for finding in (left, right) for c in finding.contributions}) < 2:
            continue
        components = set(left.affected_components) & set(right.affected_components) & known
        shared = {evidence_key(ref) for ref in left.evidence if ref.kind == "source"} & {
            evidence_key(ref) for ref in right.evidence if ref.kind == "source"}
        if components or shared:
            links.append(FindingRelation(finding_refs=[left.id, right.id], shared_components=sorted(components),
                shared_evidence=sorted(key for key, ref in evidence.items() if evidence_key(ref) in shared)))
    plan = state.get("plan")
    uncovered = plan.uncovered_requirements if plan else []
    usable = [row for row in records if row.result is not None and row.status in {"completed", "partial"}]
    status = ("failed" if plan is None or not usable and plan.assignments else "not_applicable" if not plan.assignments
        else "partial" if gaps or uncovered else "completed")
    coverage = ReusabilityCoverage(selected_investigation_ids=[a.invocation_id for a in state.get("initial_plan", [])],
        evaluated_investigation_ids=evaluated,
        completed_investigation_ids=[r.assignment.invocation_id for r in records if r.status == "completed"],
        partial_investigation_ids=[r.assignment.invocation_id for r in records if r.status == "partial"],
        failed_investigation_ids=[r.assignment.invocation_id for r in records if r.status in {"failed", "timeout"}],
        not_executed_investigation_ids=[r.assignment.invocation_id for r in records if r.status == "skipped"],
        observed_source_paths=sorted({ref.path for ref in evidence.values() if ref.kind == "source"}))
    limitations = list(dict.fromkeys([*state["limitations"], *(plan.limitations if plan else []),
        *(warning for row in records for warning in row.warnings), *(row.failure.summary for row in records if row.failure),
        "La ejecución terminada no prueba cobertura exhaustiva ni conformidad global del repositorio."]))
    summary = (f"Reusabilidad: {status}. Investigadores seleccionados: {len(coverage.selected_investigation_ids)}; "
        f"completos: {len(coverage.completed_investigation_ids)}; parciales: {len(coverage.partial_investigation_ids)}; "
        f"fallidos/no ejecutados: {len(coverage.failed_investigation_ids) + len(coverage.not_executed_investigation_ids)}. "
        f"Hallazgos/observaciones conservados: {len(findings)}. Sin revisión de aceptación ni veredicto de conformidad global.")
    result = ReusabilityResult(assessment_id=stable_id("reusability-assessment", [state["snapshot_hash"], execution.request.model_dump(mode="json")]),
        **{key: state[key] for key in ("repository_id", "commit", "snapshot_hash", "request", "plan", "consumption")},
        objective=execution.request.objective, targets=execution.request.targets, investigator_registry=state["investigator_catalog"],
        initial_plan=state.get("initial_plan", []), execution_records=state.get("execution_records", []), invocations=records,
        consolidated_findings=findings, evidence=evidence, links=links, coverage=coverage, uncovered_requirements=uncovered,
        material_gaps=gaps, status=status, termination_reason=f"assessment_{status}", summary=summary, limitations=limitations,
        duration_seconds=max(0, monotonic() - execution.started), node_transitions=[*state.get("node_transitions", []), "finalize_assessment"])
    return {"result": result, "termination_reason": result.termination_reason}
