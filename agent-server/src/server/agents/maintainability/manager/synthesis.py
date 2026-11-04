"""Manager synthesis projections and proposal checks; no graph or model invocation."""

from ....runtimes.coordination.synthesis import stable_id
from ....runtimes.repository.access import repository_relative_path
from .schemas import CoverageGap


def subordinate_tasks(record, findings, evidence):
    """Preserve subordinate identity; the manager does not reinterpret its review."""
    prefix = record.assignment.invocation_id + "/"
    return [CoverageGap(id=stable_id("subordinate", [record.assignment.investigator_id, gap.id]),
        kind="missing_coverage", coordinator=record.assignment.investigator_id, question=gap.question,
        targets=gap.targets, task_type=gap.task_type, commitments=gap.commitments,
        diagnostics=gap.diagnostics, source_assessment_invocation_id=record.assignment.invocation_id,
        subordinate_gap_ids=[gap.id], evidence_refs=[prefix + ref for ref in gap.evidence_refs if prefix + ref in evidence])
        for gap in record.result.material_gaps if gap.material]


def qualified_summary(summary, findings):
    qualified = [c["finding"] for value in findings.values() for c in value["contributions"]
        if c["finding"].get("classification") in {"conditional", "context_dependent_risk"}]
    if not qualified:
        return summary
    # Preserve host-reviewed wording instead of allowing a free-form summary to
    # promote a conditional proposal into an unconditional audit conclusion.
    return "Context-qualified audit observations:\n" + "\n".join(dict.fromkeys(
        "\n".join(filter(None, [f.get("sharing_boundary"), f.get("assessed_context"),
            f.get("adaptation_impact") or f.get("modularity_impact"), f.get("recommendation"),
            *["Condition: " + text for text in f.get("conditions", [])],
            *["Assumption: " + text for text in f.get("assumptions", [])],
            *["Unknown: " + text for text in f.get("unknowns", [])]])) for f in qualified))


def assessment_indexes(records):
    """Namespace nested references by coordinator and investigator invocation."""
    findings, evidence = {}, {}
    superseded = {r.assignment.baseline_invocation_id for r in records
        if r.result is not None and getattr(r.assignment, "baseline_invocation_id", None)}
    for record in records:
        if record.result:
            prefix = record.assignment.invocation_id + "/"
            for invocation in record.result.invocations:
                for ref in invocation.evidence:
                    evidence[prefix + invocation.assignment.invocation_id + "/" + ref.id] = ref
            for group in record.result.consolidated_findings:
                if record.assignment.invocation_id in superseded:
                    continue
                findings[prefix + group.id] = {"coordinator": record.assignment.investigator_id,
                    "invocation_id": record.assignment.invocation_id, **group.model_dump(mode="json")}
    return findings, evidence


def synthesis_context(state, request, records, findings, evidence, gaps):
    """Project the same source-backed view used by the manager's synthesis prompt."""
    compact_findings = {ref: {"coordinator": value["coordinator"], "concern": value["concern"], "status": value["status"],
        "affected_components": value["affected_components"], "limitations": value["limitations"],
        "contributions": [{"reference": c["reference"], "investigator_id": c["investigator_id"],
            "classification": c["finding"].get("classification"), "category": c["finding"].get("category"),
             "assumptions": c["finding"].get("assumptions", []), "assessed_context": c["finding"].get("assessed_context"),
             "conditions": c["finding"].get("conditions", []),
             "sharing_boundary": c["finding"].get("sharing_boundary"),
             "unknowns": c["finding"].get("unknowns", []),
             "adaptation_impact": c["finding"].get("adaptation_impact"),
             "adaptation_effort": c["finding"].get("adaptation_effort"),
             "mitigation_options": c["finding"].get("mitigation_options", []),
             "modularity_impact": c["finding"].get("modularity_impact"),
             "recommendation": c["finding"].get("recommendation"),
            "evidence_refs": [value["invocation_id"] + "/" + c["invocation_id"] + "/" + e["id"]
                for e in c["finding"]["evidence"] if e["kind"] == "source"]} for c in value["contributions"]]}
        for ref, value in findings.items()}
    return {"audit_id": state["assessment_id"], "objective": request.objective, "scope": state["scope"].model_dump(),
        "assessments": [{"invocation_id": r.assignment.invocation_id, "coordinator": r.assignment.investigator_id,
            "status": r.status, "coverage_issues": r.coverage_issues, "gap_ids": r.assignment.gap_ids,
            "summary": r.result.summary if r.result else "", "limitations": r.warnings[:8],
            "termination_reason": r.result.termination_reason if r.result else None,
            "subordinate_tasks": [g.model_dump() for g in r.result.material_gaps] if r.result else [],
            "resolved_subordinate_gap_ids": r.result.resolved_gap_ids if r.result else []} for r in records],
        "findings": compact_findings, "evidence": {k: v.model_dump() for k, v in evidence.items() if v.kind == "source"},
        "gaps": [g.model_dump() for g in gaps.values()]}


def validate_draft(draft, findings, evidence, scope, request, paths):
    """Check every proposal before any manager gap or relationship is changed."""
    for link in draft.links:
        if len(set(link.finding_refs)) < 2 or not set(link.finding_refs) <= findings.keys():
            raise ValueError("Unknown finding reference")
    for gap in draft.gaps:
        if (gap.kind not in {"quality", "contradiction"} or gap.coordinator not in scope.assessable
                or gap.source_assessment_invocation_id is not None or gap.subordinate_gap_ids or gap.commitments
                or gap.task_type != "investigation" or gap.diagnostics
                or not gap.blocking or not gap.question.strip() or not set(gap.finding_refs) <= findings.keys()
                or not set(gap.evidence_refs) <= evidence.keys()):
            raise ValueError("Invalid proposed gap")
        for target in gap.targets:
            target = repository_relative_path(target)
            scope_targets = request.dimension_targets.get(gap.coordinator, request.targets)
            if (target not in paths and not any(p.startswith(target + "/") for p in paths)
                    or scope_targets and not any(target == t or target.startswith(t + "/") for t in scope_targets)):
                raise ValueError("Inaccessible gap target")
    for link in draft.links:
        if link.kind == "contradiction" and not any(g.kind == "contradiction" and set(link.finding_refs) <= set(g.finding_refs) for g in draft.gaps):
            raise ValueError("Untracked contradiction")
    for resolution in draft.resolutions:
        if not set(resolution.evidence_refs) <= evidence.keys():
            raise ValueError("Unknown resolution evidence")
