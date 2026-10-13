"""Salvage valid findings and assemble a scoped architectural result."""

from ..repository_runtime.results import execution_results
from .context import citations_for, retain_valid_sections
from .coverage import application_coverage
from .schemas import ArchitectureResult


def assemble_result(state, context):
    report = retain_valid_sections(context.tools, state["raw"])
    coverage = application_coverage(context.tools, report)
    pending = [
        f"Application {item['path']}: {item['reason']}"
        for item in coverage
        if item["status"] != "explained"
    ]
    if report and pending:
        report = report.model_copy(
            update={
                "uncertainties": tuple(
                    dict.fromkeys((*report.uncertainties, *pending))
                )[:10]
            }
        )
    evidence = context.tools.retrieved_evidence
    inspected = tuple(
        sorted({record.file_id for record in evidence if record.kind == "source"})
    )
    complete = bool(
        report
        and report.organization
        and report.closest_architecture
        and report.explanation
        and report.closest_architecture.assessment.status != "unresolved"
        and report.explanation.status != "unresolved"
        and len(inspected) >= 2
        and not state["issues"]
        and not state["errors"]
        and not pending
    )
    status = "complete" if complete else "partial" if report else "failed"
    usage, telemetry = execution_results(
        context.tools,
        context.generate,
        state["calls"],
        state["issues"],
        context.objective_id,
    )
    limitations = (
        "Architecture describes inspected scope, not global compliance. Source-reference validation is not semantic validation.",
        "Infrastructure configuration is intended execution, not verified production deployment.",
    )
    if not complete:
        limitations += ("Incomplete or rejected sections remain unresolved.",)
    return ArchitectureResult(
        snapshot_hash=context.tools.context.input.snapshot_hash,
        completion_status=status,
        architecture=report,
        citations=citations_for(context.tools, report),
        retrieved_evidence=evidence,
        inspected_file_ids=inspected,
        application_coverage=coverage,
        reference_repairs=state["reference_repairs"],
        limitations=limitations,
        execution_issues=state["issues"],
        usage=usage,
        telemetry=telemetry,
    )
