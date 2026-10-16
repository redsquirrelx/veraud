"""Manager-specific scope, accounting, nested provenance and coverage checks."""

from ....runtimes.coordination.synthesis import evidence_key
from ....runtimes.investigation.schemas import EvidenceReference


def valid_reference(ref, tools):
    source = next((f for f in tools.accessible_snapshot.files if f.id == ref.file_id), None)
    return bool(source and ref.path == source.path and ref.content_hash == source.content_hash
        and ref.snapshot_hash == tools.context.input.snapshot_hash
        and ref.commit in {None, tools.accessible_snapshot.repository.commit}
        and (ref.kind != "source" or ref.start_line is not None and ref.end_line is not None
             and 1 <= ref.start_line <= ref.end_line <= (source.line_count or 0)))


def _validate_nested_evidence(value, invocation_id, known, check_reference):
    """Every evidence record embedded in domain analyses must match the collected ledger."""
    if isinstance(value, dict):
        if {"id", "path", "file_id", "content_hash", "snapshot_hash", "tool_call_id", "kind"} <= value.keys():
            ref = EvidenceReference.model_validate(value)
            if not check_reference(ref) or known.get((invocation_id, ref.id)) != ref:
                raise ValueError("Uncollected nested assessment evidence")
        for item in value.values():
            _validate_nested_evidence(item, invocation_id, known, check_reference)
    elif isinstance(value, list):
        for item in value:
            _validate_nested_evidence(item, invocation_id, known, check_reference)


def validate_assessment(result, assignment, *, snapshot, request, check_reference, verify_references):
    """Reject mismatched or unsupported coordinator output before it contributes knowledge."""
    if (result.repository_id != snapshot.name or result.commit != snapshot.commit or result.snapshot_hash != snapshot.snapshot_hash
            or result.objective != assignment.question or result.targets != assignment.targets):
        raise ValueError("Mismatched coordinator scope/provenance")
    if assignment.investigator_id == "reusability" and result.target_context != request.target_context:
        raise ValueError("Mismatched target context")
    _validate_accounting(result, assignment.budget)
    _validate_invocations(result, snapshot, check_reference, verify_references)
    _validate_consolidated_findings(result, check_reference)


def _validate_accounting(result, budget):
    usage = result.consumption
    if budget is None or any(getattr(usage, k) < 0 for k in ("model_calls", "tool_calls", "accounted_tokens", "estimated_tokens")):
        raise ValueError("Invalid accounting")
    if (usage.model_calls > budget.max_model_calls or usage.tool_calls > budget.max_tool_calls
            or usage.accounted_tokens > budget.max_total_tokens or usage.estimated_tokens > usage.accounted_tokens):
        raise ValueError("Usage exceeded reserved envelope")
    if len({r.assignment.invocation_id for r in result.invocations}) != len(result.invocations):
        raise ValueError("Duplicate subordinate invocation IDs")
    if any(sum(getattr(r.consumption, k) for r in result.invocations) > getattr(usage, k)
           for k in ("model_calls", "tool_calls", "accounted_tokens")):
        raise ValueError("Underreported nested usage")


def _validate_invocations(result, snapshot, check_reference, verify_references):
    known = {}
    for record in result.invocations:
        if any(getattr(record.consumption, k) < 0 for k in ("model_calls", "tool_calls", "accounted_tokens", "estimated_tokens")):
            raise ValueError("Invalid nested accounting")
        for ref in record.evidence:
            if not check_reference(ref):
                raise ValueError("Invalid nested evidence")
            known[(record.assignment.invocation_id, ref.id)] = ref
        if record.result:
            child = record.result
            if (child.snapshot_hash != snapshot.snapshot_hash or child.commit != snapshot.commit
                    or child.repository_id != snapshot.name or child.objective != record.assignment.question):
                raise ValueError("Invalid nested result provenance")
            for finding in child.findings:
                for ref in finding.evidence:
                    if known.get((record.assignment.invocation_id, ref.id)) != ref:
                        raise ValueError("Finding not in collected ledger")
                if finding.validation_status == "accepted":
                    _, mismatch = verify_references(finding.evidence)
                    if mismatch or not any(e.kind == "source" for e in finding.evidence):
                        raise ValueError("Unverifiable accepted source attribution")
            _validate_nested_evidence(child.model_dump(), record.assignment.invocation_id, known, check_reference)


def _validate_consolidated_findings(result, check_reference):
    for group in result.consolidated_findings:
        for contribution in group.contributions:
            record = next((r for r in result.invocations if r.assignment.invocation_id == contribution.invocation_id), None)
            if (not record or not record.result or contribution.investigator_id != record.assignment.investigator_id
                    or contribution.reference != f"{contribution.invocation_id}/{contribution.finding.id}"
                    or not any(f == contribution.finding and f.validation_status == "accepted" for f in record.result.findings)):
                raise ValueError("Unsupported consolidated contribution")
        available = {evidence_key(e) for c in group.contributions for e in c.finding.evidence}
        if any(evidence_key(e) not in available or not check_reference(e) for e in group.evidence):
            raise ValueError("Unsupported consolidated evidence")


def coverage_issues(result, registry):
    """Require all registered lenses to finish a planned, source-backed investigation."""
    issues = []
    if result.status != "completed" or result.material_gaps:
        issues.append("Coordinator incomplete or material gaps unresolved.")
    if {a.investigator_id for a in result.initial_plan} != set(registry):
        issues.append("Coordinator initial plan does not cover its registered investigator lenses.")
    for investigator in registry:
        if not any(r.assignment.investigator_id == investigator and r.status == "completed" and r.result and r.result.plan
                   and getattr(r.result, "status", "completed") == "completed" and not r.result.missing_information
                   and not any(h.status in {"pending", "inconclusive"} for h in r.result.hypotheses)
                   and any(e.kind == "source" for e in r.evidence) for r in result.invocations):
            issues.append(f"No completed planned source-backed investigation from {investigator}.")
    if any(g.status == "disputed" for g in result.consolidated_findings):
        issues.append("Disputed subordinate finding remains.")
    return issues
