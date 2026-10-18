"""Interpret existing blackboard records without reading a repository or rewriting claims."""

from collections import defaultdict

from ...blackboard.models import Assessment, BlackboardRecord, Evidence, Finding
from ..schemes.report import RecordReference, ReportFinding, ReportStatement

AGENT_CATEGORIES = {
    "architecture_boundary": ("maintainability", "modularity"),
    "responsibility": ("maintainability", "modularity"),
    "dependency_impact": ("maintainability", "modularity"),
    "modularity": ("maintainability", "modularity"),
    "abstraction": ("maintainability", "reusability"),
    "reuse_opportunity": ("maintainability", "reusability"),
    "component_adaptability": ("maintainability", "reusability"),
    "reusability": ("maintainability", "reusability"),
    "maintainability_manager": ("maintainability", "unspecified"),
}

ATTRIBUTE_TITLES = {
    "maintainability": "Mantenibilidad", "security": "Seguridad",
    "functional_adequacy": "Adecuación funcional",
}

SUBCHARACTERISTICS = {
    "modularity": ("Modularidad", ["Límites arquitectónicos", "Impacto de dependencias", "Distribución de responsabilidades"]),
    "reusability": ("Reusabilidad", ["Abstracciones", "Oportunidades de reutilización", "Adaptabilidad de componentes"]),
    "analysability": ("Analizabilidad", ["Comprensión del código", "Claridad diagnóstica", "Trazabilidad de ejecución"]),
    "modifiability": ("Modificabilidad", ["Escenarios de cambio", "Impacto de modificaciones", "Riesgos de cambios"]),
    "testability": ("Capacidad de prueba", ["Aislamiento para pruebas", "Escenarios de prueba", "Barreras de prueba"]),
}


def reference(record: BlackboardRecord, kind: str) -> RecordReference:
    return RecordReference(record_type=kind, record_id=record.id,
        agent_id=record.agent_id, invocation_id=record.invocation_id)


def statement(text: str, record: BlackboardRecord, kind: str) -> ReportStatement:
    return ReportStatement(text=text, source_refs=[reference(record, kind)])


def category(record: Finding | Assessment, assessments=()):
    declared = record.quality_attribute if isinstance(record, Assessment) else record.details.get("quality_attribute")
    dimension = record.details.get("subcharacteristic")
    if declared:
        if declared in SUBCHARACTERISTICS and record.agent_id in AGENT_CATEGORIES:
            return "maintainability", str(dimension or declared)
        return str(declared), str(dimension or AGENT_CATEGORIES.get(record.agent_id, ("", "unspecified"))[1])
    if record.agent_id in AGENT_CATEGORIES:
        return AGENT_CATEGORIES[record.agent_id]
    parents = {item.quality_attribute for item in assessments if record.id in item.finding_ids and item.quality_attribute}
    return (next(iter(parents)), str(dimension or "unspecified")) if len(parents) == 1 else ("unclassified", "unspecified")


def review_overrides(findings, assessments, decision_assessments=None):
    """Resolve invocation-local review references only through records in this audit."""
    aliases = {f"{item.invocation_id}/{item.local_id}": item.id for item in findings if item.local_id}
    aliases.update({item.id: item.id for item in findings})
    overrides = defaultdict(list)
    groups = defaultdict(set)
    relationships = []
    unresolved = []
    group_aliases = {}
    allowed = {a.id for a in (decision_assessments if decision_assessments is not None else assessments)}
    # Build all group aliases before resolving manager relationships. A group is
    # not a finding ID; expand its explicit original contributions.
    for assessment in assessments:
        for group in assessment.consolidated_findings:
            ids = set()
            for c in group.get("contributions", []):
                alias = c.get("reference") or f"{c.get('invocation_id')}/{c.get('finding', {}).get('id')}"
                if alias in aliases:
                    ids.add(aliases[alias])
            if group.get("id"):
                group_aliases[f"{assessment.invocation_id}/{group['id']}"] = ids
                group_aliases[f"{assessment.id}/{group['id']}"] = ids
    for assessment in assessments:
        for withdrawn in assessment.withdrawn_finding_refs:
            if withdrawn in aliases:
                if assessment.id in allowed:
                    overrides[aliases[withdrawn]].append(("withdrawn", assessment))
            else:
                unresolved.append(f"assessment:{assessment.id}:withdrawn_finding:{withdrawn}")
        for group in assessment.consolidated_findings:
            for contribution in group.get("contributions", []):
                if not isinstance(contribution, dict):
                    continue
                alias = contribution.get("reference")
                if alias is None:
                    local = contribution.get("finding", {})
                    alias = f"{contribution.get('invocation_id')}/{local.get('id')}"
                identifier = aliases.get(alias)
                if identifier is None:
                    unresolved.append(f"assessment:{assessment.id}:contribution:{alias}")
                    continue
                groups[identifier].add(f"{assessment.id}/{group.get('id', 'unknown')}")
                finding = contribution.get("finding", {})
                status = finding.get("validation_status") if isinstance(finding, dict) else None
                if status and assessment.id in allowed:
                    overrides[identifier].append((status, assessment))
                if group.get("status") == "disputed" and assessment.id in allowed:
                    overrides[identifier].append(("insufficient_evidence", assessment))
        for link in assessment.relationships:
            if assessment.id not in allowed:
                continue
            refs = link.get("finding_refs", [])
            resolved = [{aliases[item]} if item in aliases else group_aliases.get(item, set()) for item in refs]
            ids = set().union(*resolved) if resolved else set()
            if len(refs) < 2 or not all(resolved) or not ids:
                unresolved.append(f"assessment:{assessment.id}:relationship:{link.get('kind', 'unknown')}")
                continue
            relationships.append({"kind": link.get("kind", "related"), "finding_ids": sorted(set(ids)),
                "rationale": link.get("rationale", ""), "status": link.get("resolution_status", link.get("status", "observed")),
                "source_refs": [reference(assessment, "assessment")]})
    return overrides, groups, relationships, unresolved


def report_findings(findings: list[Finding], evidence: list[Evidence], assessments: list[Assessment], *, effective=None, historical=None):
    index = {item.id: item for item in evidence}
    overrides, groups, relationships, unresolved = review_overrides(findings, assessments, effective)
    historical = historical or {}
    results = []
    for finding in findings:
        attribute, dimension = category(finding, assessments)
        issues = []
        statuses = [finding.details.get("validation_status", "insufficient_evidence")]
        decisions = overrides[finding.id]
        statuses.extend(status for status, _ in decisions)
        # Contradictory judgments never become a confirmed defect by report formatting.
        if "withdrawn" in statuses:
            verification = "discarded"
        elif "accepted" in statuses and "rejected" in statuses:
            verification = "inconclusive"
            issues.append("conflicting_review_decisions")
        elif "rejected" in statuses:
            verification = "discarded"
        elif set(statuses) == {"accepted"}:
            verification = "verified"
        else:
            verification = "inconclusive"
        refs = [index[item] for item in finding.evidence_ids if item in index]
        missing = set(finding.evidence_ids) - index.keys()
        if missing:
            issues.append("unresolved_evidence_references")
            unresolved.extend(f"finding:{finding.id}:evidence:{item}" for item in sorted(missing))
        if not any(item.kind in {"source", "tool_result"} for item in refs):
            issues.append("no_technical_evidence")
        identities = {(item.snapshot_hash, item.commit) for item in refs}
        if len(identities) > 1:
            issues.append("mixed_evidence_revisions")
        investigation = finding.details.get("investigation", {})
        expected_snapshot = investigation.get("snapshot_hash")
        expected_commit = investigation.get("commit")
        if expected_snapshot and any(e.snapshot_hash != expected_snapshot or e.commit != expected_commit for e in refs):
            issues.append("evidence_investigation_revision_mismatch")
        parents = [a for a in assessments if finding.id in a.finding_ids]
        if parents and refs and not any(all((e.snapshot_hash, e.commit) == (a.snapshot_hash, a.commit) for e in refs) for a in parents):
            issues.append("evidence_assessment_revision_mismatch")
        if any(item.commit_verification == "unverified" or (
                item.commit is not None and item.commit_verification not in {"exact", "line_endings_equivalent"})
                for item in refs):
            issues.append("commit_attribution_unverified")
        if finding.kind == "violation" and finding.criterion.origin != "explicit":
            issues.append("violation_requires_explicit_criterion")
        if attribute == "unclassified":
            issues.append("quality_attribute_not_recorded")
        if issues and verification == "verified":
            verification = "inconclusive"
        details = finding.details
        classification = details.get("classification")
        strength = details.get("category") in {"useful_abstraction", "justified_boundary"}
        disposition = ("strength" if strength else "conditional_proposal" if classification == "conditional" else
            "opportunity" if classification in {"recommended", "not_recommended"} else
            "contextual_risk" if classification == "context_dependent_risk" else
            "opportunity" if details.get("category") == "missed_reuse" else
            "defect" if finding.kind == "violation" or classification in {"verified_obstacle", "verified_constraint"} or details.get("category") in
            {"unnecessary_abstraction", "coupling"} else "observation")
        assessment_ids = set(details.get("assessment_ids", []))
        domain = [a for field in ("components_investigated", "dependency_assessments") for a in investigation.get(field, [])
            if isinstance(a, dict) and a.get("id") in assessment_ids and a.get("validation_status") == "source_backed"
            and not a.get("validation_issues")]
        if disposition == "observation" and any(a.get("potentially_incompatible") or a.get("impact_kind") == "demonstrated" for a in domain):
            disposition = "defect"
        if disposition == "observation" and any(a.get("impact_kind") == "plausible_risk" for a in domain):
            disposition = "contextual_risk"
        assessed_context = details.get("assessed_context") or "\n".join(a.get("change_scenario", "") for a in domain if a.get("impact_kind") == "plausible_risk")
        original_rationale = str(details.get("review_rationale", "No consta una revisión explícita."))
        rationale = original_rationale + (" Decisión documental: " + verification + "; " + ", ".join(issues) + "." if issues else "")
        results.append(ReportFinding(
            id=finding.id, title=finding.title, quality_attribute=attribute, subcharacteristic=dimension,
            kind=finding.kind, severity=finding.severity, description=finding.description, criterion=finding.criterion,
            justification=finding.justification,
            evidence_ids=[item.id for item in refs], components=list(finding.components), impact=finding.modularity_impact,
            recommendation=finding.recommendation, verification_status=verification,
            verification_rationale=rationale, original_review_rationale=original_rationale,
            original_validation_status=str(details.get("validation_status", "insufficient_evidence")),
            lifecycle="historical" if finding.id in historical else "current", superseded_by=historical.get(finding.id, []),
            disposition=disposition, assessed_context=assessed_context, sharing_boundary=details.get("sharing_boundary", ""),
            conditions=details.get("conditions", []), assumptions=details.get("assumptions", []), unknowns=details.get("unknowns", []),
            limitations=details.get("limitations", []),
            validation_issues=issues, source_refs=[reference(finding, "finding"),
                *[reference(item, "assessment") for _, item in decisions]],
            consolidation_ids=sorted(groups[finding.id]), classification=(
                "strength" if finding.details.get("category") in {"useful_abstraction", "justified_boundary"}
                else "problem" if finding.kind == "violation" else "observation"),
            technical_details={key: value for key, value in finding.details.items()
                if key not in {"investigation", "evidence"}}))
    return results, relationships, unresolved
