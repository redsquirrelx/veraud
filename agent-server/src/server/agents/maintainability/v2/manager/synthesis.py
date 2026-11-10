"""Lossless exact grouping and observable anchors, never semantic judgments."""

import json
from itertools import combinations
from time import monotonic

from server.runtimes.coordination.synthesis import evidence_key, stable_id

from .collection import objects
from .delegation import assignment_identifier
from .schemas import AssessmentSynthesis, AuditCoverage, AuditResult, FindingRelation


def synthesize_assessments(execution, state):
    findings, evidence, groups = {}, {}, {}
    assessments = state.get("assessments", [])
    for assessment in assessments:
        evidence.update(assessment.evidence)
        for finding in assessment.findings:
            content = {key: value for key, value in finding.payload.items() if key != "id"}
            proof = sorted({evidence[ref].model_dump_json() for ref in finding.evidence_refs})
            identity = [content, proof] if proof and not finding.integrity_issues else [content, finding.origins[0].model_dump()]
            groups.setdefault(json.dumps(identity, sort_keys=True), []).append(finding)
    for key, members in sorted(groups.items()):
        members.sort(key=lambda finding: finding.origins[0].model_dump_json())
        findings[stable_id("finding", key)] = members[0].model_copy(update={
            "origins": [origin for member in members for origin in member.origins],
            "evidence_refs": sorted({ref for member in members for ref in member.evidence_refs}),
            "integrity_issues": sorted({issue for member in members for issue in member.integrity_issues})})
    snapshot = execution.tools.accessible_snapshot
    aliases = {alias: file.path for file in snapshot.files for alias in (file.id, file.path)}
    aliases.update({symbol.id: symbol.id for symbol in snapshot.symbols})
    references = {relationship.id for relationship in snapshot.relationships}
    anchors = {}
    for key, finding in findings.items():
        components, refs = set(), set()
        for value, _, _ in objects(finding.payload):
            components.update(aliases[item] for field in ("components", "affected_components", "symbol_ids")
                for item in (value[field] if isinstance(value.get(field), list) else []) if isinstance(item, str) and item in aliases)
            refs.update(item for item in (value["relationship_ids"] if isinstance(value.get("relationship_ids"), list) else [])
                if isinstance(item, str) and item in references)
        anchors[key] = components, refs, {evidence_key(evidence[ref]) for ref in finding.evidence_refs}
    links = []
    for left, right in combinations(sorted(findings), 2):
        components = anchors[left][0] & anchors[right][0]
        refs = anchors[left][1] & anchors[right][1]
        common = anchors[left][2] & anchors[right][2]
        if components or refs or common:
            links.append(FindingRelation(finding_refs=[left, right], shared_components=sorted(components),
                shared_references=sorted(refs), shared_evidence=sorted({ref for key in (left, right)
                    for ref in findings[key].evidence_refs if evidence_key(evidence[ref]) in common})))
    plan = state.get("plan")
    selected = [assignment_identifier(state["snapshot_hash"], index, assignment) for index, assignment in enumerate(plan.assignments if plan else [])]
    coverage = AuditCoverage(selected_assignment_ids=selected,
        evaluated_assignment_ids=sorted(a.assignment_id for a in assessments if a.evaluation_performed and a.status in {"completed", "partial"}),
        completed_assignment_ids=sorted(a.assignment_id for a in assessments if a.status == "completed"),
        partial_assignment_ids=sorted(a.assignment_id for a in assessments if a.status == "partial"),
        failed_assignment_ids=sorted(a.assignment_id for a in assessments if a.status in {"failed", "timeout"}),
        not_executed_assignment_ids=sorted(a.assignment_id for a in assessments if a.status == "skipped"),
        observed_source_paths=sorted({ref.path for ref in evidence.values() if ref.kind == "source"}),
        uncovered_requirements=list(dict.fromkeys([*(plan.uncovered_requirements if plan else []),
            *(item for a in assessments for item in a.inconclusive if isinstance(item, str))])))
    severity = {value: index for index, value in enumerate(("critical", "high", "medium", "low", "info"))}
    synthesis = AssessmentSynthesis(findings=dict(sorted(findings.items(), key=lambda item: (
        severity.get(str(item[1].payload.get("severity")), 5), item[0]))), evidence=dict(sorted(evidence.items())), links=links,
        coverage=coverage, issues=sorted(state.get("collection_issues", []), key=lambda issue: issue.model_dump_json()))
    return {"synthesis": synthesis}


def finalize_audit(execution, state):
    synthesis, plan = state["synthesis"], state.get("plan")
    assessments = state.get("assessments", [])
    usable = [a for a in assessments if a.status in {"completed", "partial"}]
    if plan is None or not usable and (plan.assignments or synthesis.issues):
        status = "failed"
    elif not plan.assignments:
        status = "not_applicable"
    elif (all(a.status == "completed" for a in assessments) and not synthesis.issues
        and not synthesis.coverage.uncovered_requirements and not any(a.inconclusive for a in assessments)):
        status = "completed"
    else:
        status = "partial"
    limitations = list(dict.fromkeys([*state.get("limitations", []), *(plan.limitations if plan else []),
        *(issue.message for issue in synthesis.issues), "No se infiere conformidad global por ausencia de hallazgos."]))
    labels = {"completed": "Completada para las asignaciones seleccionadas; no implica cobertura exhaustiva del repositorio.",
        "partial": "Parcial: existen tareas pendientes, limitaciones de integridad o resultados solo de planificación.",
        "failed": "Fallida: no se obtuvo una evaluación utilizable de las asignaciones seleccionadas.",
        "not_applicable": "Sin coordinadores aplicables según el plan; no se realizó una evaluación técnica."}
    summary = (f"{labels[status]} Coordinadores seleccionados: {len(plan.assignments) if plan else 0}; "
        f"ejecuciones completas: {len(synthesis.coverage.completed_assignment_ids)}; "
        f"parciales: {len(synthesis.coverage.partial_assignment_ids)}; "
        f"fallidas/no ejecutadas: {len(synthesis.coverage.failed_assignment_ids) + len(synthesis.coverage.not_executed_assignment_ids)}. "
        f"Observaciones conservadas: {len(synthesis.findings)}. No se infiere conformidad global.")
    result = AuditResult(**synthesis.model_dump(), assessment_id=stable_id("audit", [state["snapshot_hash"], state["request"].model_dump(mode="json")]),
        **{key: state[key] for key in ("repository_id", "commit", "snapshot_hash", "request", "coordinator_catalog", "consumption")},
        objective=state["request"].objective, targets=state["request"].targets, plan=plan,
        coordinator_results=state.get("coordinator_results", []), assessments=assessments, status=status,
        termination_reason=f"audit_{status}", summary=summary, limitations=limitations,
        duration_seconds=max(0, monotonic() - execution.started), node_transitions=[*state.get("node_transitions", []), "finalize_audit"])
    return {"result": result, "termination_reason": result.termination_reason}
