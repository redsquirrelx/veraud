"""Salvage valid findings and assemble a scoped architectural result."""

from ....runtimes.repository.results import execution_results
from .context import citations_for, retain_valid_sections
from .coverage import (
    application_coverage,
    relationship_coverage,
    relationship_recovery_tasks,
)
from .schemas import ArchitectureResult


def assemble_result(state, context):
    report = retain_valid_sections(context.tools, state["raw"])
    coverage = application_coverage(context.tools, report)
    relationships = relationship_coverage(context.tools, report)
    files = {
        source.id: source.path for source in context.tools.accessible_snapshot.files
    }
    actions = state.get("relationship_actions", {})
    remaining_tasks = relationship_recovery_tasks(context.tools, report, actions)
    units = {unit.name: unit for unit in report.organization} if report else {}
    exhausted = (
        state["calls"]
        >= min(
            context.limits.max_model_calls,
            context.tools.context.input.budget.max_model_calls,
        )
        or state["tool_calls"]
        >= min(
            context.limits.max_tool_calls,
            context.tools.context.input.budget.max_tool_calls,
        )
        or context.tools.context.elapsed_seconds
        >= context.tools.context.input.budget.max_elapsed_seconds
    )
    investigations = (
        {entry.unit_name: entry for entry in report.relationship_investigations}
        if report
        else {}
    )
    sources = {
        record.id: record.file_id
        for record in context.tools.retrieved_evidence
        if record.kind == "source"
    }
    for item in relationships:
        if item["status"] not in {"unresolved", "uninvestigated"}:
            continue
        entry = investigations.get(item["unit_name"])
        own_files = set(units[item["unit_name"]].file_ids)
        justified = bool(
            entry
            and entry.resolution_blocker
            and entry.blocker_reason
            and own_files.intersection(entry.examined_file_ids).intersection(
                sources.values()
            )
            and any(
                sources.get(identifier) in own_files
                for identifier in entry.assessment.evidence_ids
            )
        )
        paths = set(item["pending_paths"]) | {
            files[file_id]
            for file_id in units[item["unit_name"]].file_ids
            if file_id in files
        }
        failures = [
            f"{key}: {value}"
            for key, value in actions.items()
            if value != "ok"
            and (
                key == "search:" + item["unit_name"]
                or key.removeprefix("read:") in paths
            )
        ]
        if failures:
            item.update(
                resolution_blocker="source_unavailable",
                blocker_reason="; ".join(failures)[:700],
            )
        elif exhausted and (
            not justified
            or any(task["unit"] == item["unit_name"] for task in remaining_tasks)
        ):
            item.update(
                resolution_blocker="budget_exhausted",
                blocker_reason="Model, tool or time budget was exhausted before all directed recovery tasks could be completed.",
            )
        elif not justified:
            item.update(
                resolution_blocker="assessment_incomplete",
                blocker_reason="The model did not resolve this boundary or provide an adequate source-backed justification after the available recovery attempts.",
            )
    pending = [
        f"Application {item['path']}: {item['reason']}"
        for item in coverage
        if item["status"] != "explained"
    ]
    pending.extend(
        f"Module {item['unit_name']}: {item['reason']} Pending paths: {item['pending_paths'][:8]}"
        for item in relationships
        if item["status"] in {"uninvestigated", "unresolved"}
    )
    if report and pending:
        report = report.model_copy(
            update={
                "uncertainties": tuple(
                    dict.fromkeys((*report.uncertainties, *pending))
                )[:16]
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
        relationship_coverage=relationships,
        reference_repairs=state["reference_repairs"],
        limitations=limitations,
        execution_issues=state["issues"],
        usage=usage,
        telemetry=telemetry,
    )
