"""Assemble orientation results from validated sections and delivered evidence."""

from server.project_analysis.project_orientation.context import retain_valid_sections
from server.project_analysis.project_orientation.schemas import OrientationResult
from server.runtimes.repository.results import execution_results


def assemble_result(state, context):
    orientation = retain_valid_sections(context.tools, state["raw"])
    evidence = context.tools.retrieved_evidence
    inspected = tuple(
        sorted({record.file_id for record in evidence if record.kind == "source"})
    )
    complete = bool(
        orientation
        and orientation.project_type
        and orientation.purpose
        and orientation.project_type.status != "unresolved"
        and orientation.purpose.status != "unresolved"
        and orientation.starting_points
        and inspected
        and not state["issues"]
        and not state["errors"]
    )
    status = "complete" if complete else "partial" if orientation else "failed"
    limitations = (
        "Orientation covers selected technical files, not the entire repository. Source access validation does not prove semantic sufficiency.",
    )
    if not complete:
        limitations += ("Missing, invalid, or uninspected sections remain unresolved.",)
    usage, telemetry = execution_results(
        context.tools, context.generate, state["calls"], state["issues"]
    )
    result = OrientationResult(
        snapshot_hash=context.tools.context.input.snapshot_hash,
        completion_status=status,
        orientation=orientation,
        retrieved_evidence=evidence,
        inspected_file_ids=inspected,
        limitations=limitations,
        execution_issues=state["issues"],
        usage=usage,
        telemetry=telemetry,
    )
    context.tools.context.require_snapshot(result.snapshot_hash)
    return result
