"""Host-derived completion and verdict cannot silently accept unreviewed claims."""

from ....runtimes.repository.results import execution_results
from ....runtimes.repository.schemas import ExecutionIssue
from ....services.repository_analysis.context import create_identifier
from ..project_architecture.schemas import SourceCitation
from .schemas import SemanticValidationResult


def assemble_result(state, context):
    issues = state["issues"]
    if state["errors"] and not any(
        issue.category == "invalid_findings" for issue in issues
    ):
        issues = (
            *issues,
            ExecutionIssue(
                id=create_identifier(
                    "issue", context.objective_id, state["calls"], "invalid_findings"
                ),
                stage="semantic_validation",
                category="invalid_findings",
                message="; ".join(state["errors"])[:2000],
            ),
        )
    findings = tuple(state["findings"].values())
    pending = tuple(
        target.id for target in state["targets"] if target.id not in state["findings"]
    )
    complete = bool(findings and not pending and not issues and not state["errors"])
    status = "complete" if complete else "partial" if findings else "failed"
    verdict = (
        "revisions_needed"
        if any(item.verdict in {"overstated", "contradicted"} for item in findings)
        else "needs_evidence"
        if any(item.verdict == "insufficient_evidence" for item in findings)
        else "accepted"
        if complete
        else "inconclusive"
    )
    files = {source.id: source for source in context.tools.accessible_snapshot.files}
    cited = {
        identifier
        for finding in findings
        for identifier in (
            *finding.evidence_ids,
            *(finding.correction.evidence_ids if finding.correction else ()),
        )
    }
    citations = tuple(
        SourceCitation(
            evidence_id=record.id,
            file_id=record.file_id,
            path=files[record.file_id].path,
            start_line=record.start_line,
            end_line=record.end_line,
            content_hash=record.content_hash,
        )
        for record in context.tools.retrieved_evidence
        if record.id in cited
    )
    usage, telemetry = execution_results(
        context.tools,
        context.generate,
        state["calls"],
        issues,
        context.objective_id,
    )
    return SemanticValidationResult(
        snapshot_hash=context.original.snapshot_hash,
        report_hash=state["report_hash"],
        original_result=context.original,
        completion_status=status,
        verdict=verdict,
        selected_target_ids=tuple(target.id for target in state["selected"]),
        pending_target_ids=pending,
        findings=findings,
        citations=citations,
        retrieved_evidence=context.tools.retrieved_evidence,
        execution_issues=issues,
        limitations=(
            "Semantic verdicts are model judgments over independently inspected scope, not proofs of repository-wide correctness.",
            "Unreviewed claims remain pending; proposed corrections do not mutate the architectural report.",
        ),
        usage=usage,
        telemetry=telemetry,
    )
