"""Neutral projections of finalized investigations and verifiable follow-up progress.

Concrete coordinators supply analysis/binding field names. This module never imports
investigators or treats a model's raw critical review as an authoritative decision.
"""

from server.contracts.audit import InvestigationCommitment

from .synthesis import evidence_key, normalized, stable_id


def subjects(analysis):
    ids = [getattr(analysis, key, None) for key in ("declaration_id", "component_id", "group_id")]
    for dependency in getattr(analysis, "dependencies", []):
        ids.extend([dependency.source_id, dependency.target_id])
    return sorted({value for value in ids if value})


def analysis_id(analysis):
    return getattr(analysis, "id", None) or analysis.group_id


def covered(evidence, file_id, start, end):
    if start is None or end is None:
        return False
    cursor = start
    for ref in sorted((e for e in evidence if e.kind == "source" and e.file_id == file_id), key=lambda e: e.start_line):
        if ref.start_line > cursor:
            break
        cursor = max(cursor, ref.end_line + 1)
    return cursor > end


def project(record, analysis_fields, binding_fields):
    """Retain host states, bounded domain reasoning and namespaced evidence pointers."""
    result = record.result
    if result is None:
        return {}
    analyses = [a for field in analysis_fields for a in getattr(result, field, [])]
    hypotheses = {h.id: h for h in result.hypotheses}
    planned = result.plan.hypotheses if result.plan else []
    commitments = []
    for hypothesis in planned:
        ids = sorted({i for field in binding_fields for i in getattr(hypothesis, field, [])})
        linked = [a for a in analyses if getattr(a, "hypothesis_id", None) == hypothesis.id]
        ids = ids or sorted({i for a in linked for i in subjects(a)})
        if ids:
            commitments.append(commitment(record, hypothesis.id, hypothesis.question, ids, linked))
    represented = {i for c in commitments for i in c.assessment_ids}
    for analysis in analyses:
        if analysis_id(analysis) not in represented:
            commitments.append(commitment(record, getattr(analysis, "hypothesis_id", None),
                record.assignment.question, subjects(analysis), [analysis]))
    keys = ("id", "hypothesis_id", "component_id", "declaration_id", "group_id", "conclusion", "cohesion",
        "validation_status", "validation_issues", "unknowns", "conditions", "proposed_boundary", "constraint_key",
        "assessed_context", "schema_dependency_basis", "schema_adaptation_analysis", "adaptation_impact",
        "seam_analysis", "counterevidence_analysis", "observed_facts", "limitations", "impact_kind", "consequence")
    coverage = getattr(result, "coverage", None)
    coverage = coverage.model_dump() if coverage is not None else getattr(result, "investigation_coverage", {})
    unassessed = {i for key, values in coverage.items() if key.startswith("unassessed_") for i in values}
    cleared = {i for c in commitments if c.hypothesis_id in hypotheses
        and hypotheses[c.hypothesis_id].status == "discarded" and record.status == "completed"
        and not c.validation_issues for i in c.subject_ids if i not in unassessed}
    return {"termination_reason": result.termination_reason, "cleared_subject_ids": sorted(cleared),
        "hypotheses": [h.model_dump() | {"evidence_refs": [f"{record.assignment.invocation_id}/{i}" for i in h.evidence_ids]}
            for h in hypotheses.values()],
        "hypothesis_validation_issues": getattr(result, "hypothesis_validation_issues", {}),
        "analyses": [{key: getattr(a, key) for key in keys if hasattr(a, key)} | {"id": analysis_id(a),
            "subject_ids": subjects(a), "evidence_refs": [f"{record.assignment.invocation_id}/{e.id}" for e in getattr(a, "evidence", [])]}
            for a in analyses],
        "commitments": [c.model_dump() for c in commitments],
        "coverage": {key: value for key, value in coverage.items() if not key.startswith("selected_")},
        "evaluation_evidence_status": getattr(result, "evaluation_evidence_status", None),
        "pending_evaluation_evidence_ids": getattr(result, "pending_evaluation_evidence_ids", []),
        "tool_failures": getattr(result, "tool_failures", [])}


def commitment(record, hypothesis_id, question, ids, analyses):
    refs = [e for a in analyses for e in getattr(a, "evidence", [])]
    issues = list(dict.fromkeys(i for a in analyses for i in getattr(a, "validation_issues", [])))
    issues += getattr(record.result, "hypothesis_validation_issues", {}).get(hypothesis_id, [])
    return InvestigationCommitment(source_invocation_id=record.assignment.invocation_id,
        hypothesis_id=hypothesis_id, question=question, subject_ids=ids,
        assessment_ids=[analysis_id(a) for a in analyses], paths=sorted({e.path for e in refs}),
        boundary="\n".join(sorted({getattr(a, "proposed_boundary", "") for a in analyses})).strip(),
        assessed_context="\n".join(sorted({getattr(a, "assessed_context", "") for a in analyses})).strip(),
        validation_issues=list(dict.fromkeys(issues)))


def task_specs(record, projection, source_issue_tokens, make_question):
    """Collapse diagnostic strings into subject-bound tasks, retaining every diagnostic."""
    result = record.result
    if result is None:
        return []
    hypotheses = {h["id"]: h for h in projection["hypotheses"]}
    analyses = projection["analyses"]
    specs = []
    for value in projection["commitments"]:
        c = InvestigationCommitment.model_validate(value)
        linked = [a for a in analyses if a["id"] in c.assessment_ids]
        unresolved = (c.validation_issues or not linked or any(a.get("conclusion", a.get("cohesion")) in {"unknown", "inconclusive"}
            or a.get("validation_status") != "source_backed" for a in linked))
        hypothesis = hypotheses.get(c.hypothesis_id)
        if record.status == "completed" and hypothesis and hypothesis["status"] in {"confirmed", "discarded"} and not c.validation_issues:
            continue
        if not unresolved and (not hypothesis or hypothesis["status"] in {"confirmed", "discarded"}):
            continue
        body_read = set(c.subject_ids) <= set(projection.get("source_inspected_subject_ids", []))
        source = (not linked and not body_read) or any(any(token in issue for token in source_issue_tokens)
            for issue in c.validation_issues)
        task = ("external_context" if result.termination_reason == "unverifiable" else
            "deferred_work" if not linked and not body_read and result.termination_reason in {"iteration_limit", "model_call_limit", "tool_call_limit", "time_limit"}
            else "source_inspection" if source else "validation_repair")
        question = make_question(c, task)
        identity = [record.assignment.investigator_id, c.subject_ids, c.question, task]
        specs.append({"id": stable_id("task", identity), "kind": "missing_evidence", "investigator_id": record.assignment.investigator_id,
            "question": question, "targets": record.assignment.targets, "task_type": task, "commitments": [c],
            "evidence_refs": sorted({ref for a in linked for ref in a["evidence_refs"]})})
    covered_ids = {identifier for spec in specs for c in spec["commitments"] for identifier in
        [*c.subject_ids, *c.assessment_ids, *([c.hypothesis_id] if c.hypothesis_id else [])]}
    covered_ids.update(f.id for f in result.findings if set(getattr(f, "assessment_ids", [])) & covered_ids
        or getattr(f, "group_id", None) in covered_ids)
    remaining = [text for text in result.missing_information if not (specs
        and text.startswith(("Resolve ", "Inspect ", "Hypothesis ")) and any(i in text for i in covered_ids))]
    if remaining and result.plan and (not record.assignment.gap_ids or record.assignment.commitments):
        question = record.assignment.commitments[0].question if record.assignment.commitments else record.assignment.question
        specs.append({"id": stable_id("missing", [record.assignment.investigator_id, question,
            sorted(record.assignment.targets)]), "kind": "missing_evidence", "investigator_id": record.assignment.investigator_id,
            "question": "Resolve remaining evidence gaps for: " + question,
            "diagnostics": remaining,
            "targets": record.assignment.targets, "task_type": "external_context" if result.termination_reason == "unverifiable" else "investigation"})
    return specs


def commitment_resolved(required, projection):
    """A new UUID or an assertion of completion cannot replace a bound assessment."""
    wanted = set(required.subject_ids)
    analyses = [a for a in projection.get("analyses", []) if set(a["subject_ids"]) & wanted]
    supported = set(projection.get("cleared_subject_ids", [])) | {i for a in analyses if a.get("validation_status") == "source_backed" and not a.get("validation_issues")
        and a.get("conclusion", a.get("cohesion")) not in {"unknown", "inconclusive"} for i in a["subject_ids"]}
    # Explicit source-backed clearances have no assessment. They still need a final
    # hypothesis bound to those same subjects in the returned plan.
    bound = [c for c in projection.get("commitments", []) if wanted <= set(c["subject_ids"])]
    final = {h["id"]: h for h in projection.get("hypotheses", [])}
    if not bound:
        return False
    for c in bound:
        if c["validation_issues"]:
            return False
        h = final.get(c["hypothesis_id"])
        if c["hypothesis_id"] and (not h or h["status"] not in {"confirmed", "discarded"}):
            return False
        if required.hypothesis_id and normalized(c["question"]) != normalized(required.question):
            return False
    return bool(wanted) and wanted <= supported and all(
        not required.boundary or c["boundary"] == required.boundary for c in bound) and all(
        not required.assessed_context or c["assessed_context"] == required.assessed_context for c in bound)


def validation_progress(gap, record, records, project_record):
    """Permit same-source closure only for a previously invalid, now valid bound task."""
    if gap.task_type != "validation_repair" or not gap.commitments or not record.result:
        return False
    current = project_record(record)
    for required in gap.commitments:
        prior = next((r for r in records if r.assignment.invocation_id == required.source_invocation_id
            and r.assignment.round < record.assignment.round), None)
        if not prior or not prior.result or commitment_resolved(required, project_record(prior)) or not commitment_resolved(required, current):
            return False
        # The repaired result must still cite inspected source, not only metadata.
        if not any(e.kind == "source" for e in record.evidence):
            return False
    return True


def new_source(resolution, record, records, index):
    known = {evidence_key(e) for r in records if r.assignment.round < record.assignment.round for e in r.evidence if e.kind == "source"}
    return any(ref in index and evidence_key(index[ref]) not in known for ref in resolution.evidence_refs)
