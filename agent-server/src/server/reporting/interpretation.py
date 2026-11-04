"""Explicit lineage and commitment projection; original audit judgments stay immutable."""

import hashlib
import json

from server.reporting.knowledge import AGENT_CATEGORIES, reference
from server.reporting.schemas import CoverageCommitment, ReportDecision
from server.services.audit_diagnostics import execution_records

GENERATOR_VERSION = "2.2.1"
ANALYSIS_FIELDS = ("components_investigated", "unresolved_component_assessments", "abstractions_investigated",
    "examined_groups", "examined_constraints", "dependency_assessments", "component_assessments",
    "abstraction_assessments", "reuse_assessments", "adaptation_assessments")


def decision(rule, outcome, reason, sources, paths):
    identity = json.dumps([rule, outcome, [(s.record_type, s.record_id) for s in sources], paths], sort_keys=True)
    return ReportDecision(id="decision:" + hashlib.sha256(identity.encode()).hexdigest()[:20], rule=rule,
        outcome=outcome, reason=reason, source_refs=sources, output_paths=paths)


def effective_view(assessments, findings):
    """Only an explicit, valid cumulative continuation supersedes an assessment."""
    aliases = {a.id: a for a in assessments}
    aliases.update({a.local_id: a for a in assessments if a.local_id})
    aliases.update({a.details["report"]["assessment_id"]: a for a in assessments
        if isinstance(a.details.get("report"), dict) and a.details["report"].get("assessment_id")})
    historical, replacements, issues, decisions = set(), {}, [], []
    for current in assessments:
        report = current.details.get("report", {})
        baseline_id = report.get("baseline_assessment_id")
        if not baseline_id:
            continue
        previous = aliases.get(baseline_id)
        old = previous.details.get("report", {}) if previous else {}
        old_calls = {r["assignment"]["invocation_id"]: r for r in old.get("invocations", [])}
        calls = {r["assignment"]["invocation_id"]: r for r in report.get("invocations", [])}
        valid = (previous is not None and previous.id != current.id and previous.created_at <= current.created_at
            and (previous.agent_id, previous.repository_id, previous.commit, previous.snapshot_hash, previous.targets)
            == (current.agent_id, current.repository_id, current.commit, current.snapshot_hash, current.targets)
            and bool(old_calls) and old.get("initial_plan") == report.get("initial_plan")
            and all(calls.get(key) == value for key, value in old_calls.items())
            and set(previous.resolved_gap_ids) <= set(current.resolved_gap_ids))
        # A claimed resolution must be retained in the cumulative result; absence
        # from a new list is not itself evidence that a prior gap was closed.
        if valid:
            valid = all(g.get("id") in set(current.resolved_gap_ids) or any(
                c.get("id") == g.get("id") for c in current.gaps) for g in previous.gaps)
        if not valid:
            issues.append(f"assessment:{current.id}:invalid_continuation:{baseline_id}")
            decisions.append(decision("explicit_cumulative_continuation", "unresolved",
                "La continuación no acredita identidad, recibos históricos y conservación/resolución de brechas.",
                [reference(current, "assessment")], ["quality_results.attributes"]))
            continue
        historical.add(previous.id)
        replacements[previous.id] = current.id
        decisions.append(decision("explicit_cumulative_continuation", "superseded",
            "La evaluación acumulada conserva los recibos y el alcance; la anterior permanece como antecedente.",
            [reference(previous, "assessment"), reference(current, "assessment")], ["quality_results.attributes"]))
    # Branches are ambiguous; do not let timestamps choose an authoritative result.
    for previous in set(replacements):
        baseline_aliases = {aliases[previous].id, aliases[previous].local_id, aliases[previous].details.get("report", {}).get("assessment_id")} - {None}
        successors = [a for a in assessments if a.details.get("report", {}).get("baseline_assessment_id") in baseline_aliases]
        if len(successors) > 1:
            historical.discard(previous)
            replacements.pop(previous, None)
            issues.append(f"assessment:{previous}:ambiguous_continuation")
    for origin in list(replacements):
        seen, cursor = set(), origin
        while cursor in replacements and cursor not in seen:
            seen.add(cursor)
            cursor = replacements[cursor]
        if cursor in seen:
            for identifier in seen:
                historical.discard(identifier)
                replacements.pop(identifier, None)
            issues.append(f"assessment:{origin}:continuation_cycle")
    decisions = [d for d in decisions if d.outcome != "superseded" or d.source_refs[0].record_id in historical]
    inactive_findings = {}
    by_id = {a.id: a for a in assessments}
    for old_id, new_id in replacements.items():
        old, new = by_id[old_id], by_id[new_id]
        old_calls = {r["assignment"]["invocation_id"] for r in old.details["report"].get("invocations", [])}
        new_calls = [r for r in new.details["report"].get("invocations", []) if r["assignment"]["invocation_id"] not in old_calls]
        for call in new_calls:
            for commitment in call["assignment"].get("commitments", []):
                if not set(call["assignment"].get("gap_ids", [])) & set(new.resolved_gap_ids):
                    continue
                prior = [f for f in findings if f.invocation_id == commitment.get("source_invocation_id")]
                later = [f for f in findings if f.invocation_id == call["assignment"]["invocation_id"]]
                for f in prior:
                    key = finding_identity(f)
                    matching = [n.id for n in later if key is not None and finding_identity(n) == key]
                    bound = bool(set(commitment.get("subject_ids", [])) & set(f.components)
                        or set(commitment.get("assessment_ids", [])) & set(f.details.get("assessment_ids", []))
                        or f.details.get("group_id") in commitment.get("subject_ids", []))
                    cleared = bound and any(h.get("status") == "discarded" and h.get("question") == commitment.get("question")
                        for h in (call.get("result") or {}).get("hypotheses", []))
                    if matching or cleared:
                        inactive_findings[f.id] = matching
                        decisions.append(decision("resolved_same_subject_reassessment", "historical",
                            "Un seguimiento resuelto aporta la misma identidad/contexto o descarta explícitamente el compromiso original.",
                            [reference(f, "finding"), *[reference(n, "finding") for n in later if n.id in matching]],
                            [f"quality_results.findings/{f.id}", "consolidated_risks"]))
    return [a for a in assessments if a.id not in historical], historical, inactive_findings, issues, decisions


def finding_identity(finding):
    details = finding.details
    identity = details.get("stable_id") or details.get("group_id")
    if not identity:
        return None
    return (finding.agent_id, identity, tuple(sorted(finding.components)), details.get("category"),
        details.get("assessed_context", ""), details.get("sharing_boundary", ""),
        tuple(sorted(details.get("conditions", []))), tuple(sorted(details.get("assumptions", []))))


def coverage_projection(records, effective_assessments):
    rows = []
    active_invocations = {r["assignment"]["invocation_id"] for a in effective_assessments
        for r in a.details.get("report", {}).get("invocations", [])}
    repairs = [c for a in effective_assessments for r in a.details.get("report", {}).get("invocations", [])
        if set(r["assignment"].get("gap_ids", [])) & set(a.resolved_gap_ids) for c in r["assignment"].get("commitments", [])]
    sources = {r.id: reference(r, kind) for kind, items in (("assessment", records["assessments"]),
        ("evidence", records["evidence"]), ("finding", records["findings"])) for r in items}
    for execution in execution_records(records["assessments"], records["evidence"], records["findings"]):
        report = execution["report"]
        plan = report.get("plan")
        if not isinstance(plan, dict):
            if execution["agent_id"] in AGENT_CATEGORIES and execution["agent_id"] not in {"modularity", "reusability", "maintainability_manager"}:
                rows.append(CoverageCommitment(invocation_id=execution["invocation_id"], agent_id=execution["agent_id"],
                    question=report.get("objective", "No se publicó un plan de investigación."),
                    status="skipped" if execution["status"] == "skipped" else "not_evaluated",
                    source_refs=[sources[s] for s in execution["source_record_ids"] if s in sources]))
            continue
        analyses = [a for field in ANALYSIS_FIELDS for a in report.get(field, []) if isinstance(a, dict)]
        final = {h["id"]: h for h in report.get("hypotheses", [])}
        for planned in plan.get("hypotheses", []):
            h = final.get(planned["id"], {})
            ids = sorted({i for key in ("declaration_ids", "component_ids", "group_ids") for i in planned.get(key, [])})
            if not ids and execution["agent_id"] in {"responsibility", "dependency_impact", "architecture_boundary"}:
                ids = sorted(set(plan.get("components", [])))
            linked = [a for a in analyses if a.get("hypothesis_id") == planned["id"] or a.get("component_id") in ids]
            issues = list(dict.fromkeys([*report.get("hypothesis_validation_issues", {}).get(planned["id"], []),
                *[i for a in linked for i in a.get("validation_issues", [])]]))
            if any(a.get("validation_status") not in {None, "source_backed"}
                    or a.get("conclusion", a.get("cohesion")) in {"unknown", "inconclusive"} for a in linked):
                issues.append("assessment_not_source_backed_or_inconclusive")
            unassessed = {i for key, values in report.get("coverage", {}).items() if key.startswith("unassessed_") for i in values}
            citations = set(h.get("evidence_ids", [])) | {i for a in linked for key in
                ("evidence_ids", "supporting_evidence_ids", "demonstration_evidence_ids", "seam_evidence_ids") for i in a.get(key, [])}
            citations.update(e["id"] for a in linked for e in a.get("evidence", []) if isinstance(e, dict) and "id" in e)
            evidence = [e for e in records["evidence"] if e.invocation_id == execution["invocation_id"] and e.kind == "source"
                and (e.id in citations or e.local_id in citations)]
            resolved = (h.get("status") in {"confirmed", "discarded"} and not issues and not set(ids) & unassessed
                and report.get("evaluation_evidence_status") != "stale" and not report.get("pending_evaluation_evidence_ids")
                and bool(evidence))
            status = ("discarded" if h.get("status") == "discarded" else "evaluated") if resolved else (
                "skipped" if execution["status"] == "skipped" else "deferred" if report.get("termination_reason") in
                {"iteration_limit", "round_limit", "model_call_limit", "tool_call_limit", "token_limit", "time_limit"} else "pending")
            repaired = {i for c in repairs if c.get("source_invocation_id") == execution["invocation_id"]
                and (c.get("hypothesis_id") == planned["id"] or c.get("hypothesis_id") is None
                    and set(c.get("assessment_ids", [])) & {a.get("id") for a in linked}) for i in c.get("subject_ids", [])}
            for subject_ids in ([identifier] for identifier in ids) if ids else [[]]:
                rows.append(CoverageCommitment(invocation_id=execution["invocation_id"], agent_id=execution["agent_id"],
                    hypothesis_id=planned["id"], question=planned.get("question", ""), subject_ids=subject_ids, status=status,
                    final_hypothesis_status=h.get("status"), assessment_ids=[a.get("id", a.get("group_id", "")) for a in linked],
                    validation_issues=issues, evidence_ids=[e.id for e in evidence],
                    lifecycle="historical" if subject_ids and set(subject_ids) <= repaired else
                        "current" if not active_invocations or execution["invocation_id"] in active_invocations else "historical",
                    source_refs=[sources[s] for s in execution["source_record_ids"] if s in sources]))
    return rows
