"""Evidence provenance, accepted-fact preservation, coverage, and handoff checks."""

from pydantic import BaseModel

from .context import walk_contracts
from .schemas import (
    AnalysisClaim,
    InvestigationCoverage,
    InvestigationOutcome,
    InvestigationResult,
    ProjectAnalysisReport,
    ReportSelection,
)
from .tools import RepositoryToolset

COLLECTION_FIELDS = {
    "project_identification": "project_identification",
    "functional_components": "components",
    "main_flows": "flows",
    "component_relationships": "component_relationships",
    "integrations_and_state": "integrations",
    "testing": "testing",
    "claims": "claims",
    "open_questions": "open_questions",
}


def accepted_content(findings):
    content = {}
    for report_field, finding_field in COLLECTION_FIELDS.items():
        records = {}
        for finding in findings:
            for record in getattr(finding, finding_field):
                if record.id in records and records[record.id] != record:
                    raise ValueError(f"Conflicting accepted fact: {record.id}")
                records[record.id] = record
        content[report_field] = tuple(records.values())
    return content


def investigation_coverage(tools, plan, findings):
    statuses = {finding.investigation_id: finding.status for finding in findings}
    objectives = {objective.id: objective for objective in plan.objectives}
    source_ids = {
        record.file_id for record in tools.retrieved_evidence if record.kind == "source"
    }
    snapshot = tools.accessible_snapshot
    return InvestigationCoverage(
        selected_project_ids=tuple(
            sorted({objective.project_id for objective in plan.objectives})
        ),
        investigated_project_ids=tuple(
            sorted({objectives[identifier].project_id for identifier in statuses})
        ),
        inspected_file_ids=tuple(sorted(source_ids)),
        investigated_entrypoint_ids=tuple(
            sorted(
                {
                    seed
                    for identifier in statuses
                    for seed in objectives[identifier].seed_entity_ids
                    if seed in {entrypoint.id for entrypoint in snapshot.entrypoints}
                }
            )
        ),
        planned_investigation_ids=tuple(objectives),
        completed_investigation_ids=tuple(
            identifier
            for identifier in objectives
            if statuses.get(identifier) == "completed"
        ),
        incomplete_investigation_ids=tuple(
            identifier
            for identifier in objectives
            if statuses.get(identifier) == "incomplete"
        ),
        pending_investigation_ids=tuple(
            identifier for identifier in objectives if identifier not in statuses
        ),
        deferred_decisions=tuple(
            decision
            for decision in plan.decisions
            if decision.disposition == "deferred"
        ),
        limitations=tuple(
            dict.fromkeys(
                (
                    *tools.context.snapshot.coverage.limitations,
                    *(
                        limitation
                        for finding in findings
                        for limitation in finding.limitations
                    ),
                    "Investigation coverage is planned-scope coverage, not exhaustive repository understanding.",
                )
            )
        ),
    )


def assemble_report(tools, plan, findings, selection: ReportSelection | None = None):
    content = accepted_content(findings)
    if selection is not None:
        for name, records in content.items():
            selected_ids = getattr(selection, name)
            by_id = {record.id: record for record in records}
            if len(selected_ids) != len(by_id) or set(selected_ids) != set(by_id):
                raise ValueError(
                    f"Report selection must preserve exactly the accepted {name} IDs."
                )
            content[name] = tuple(by_id[identifier] for identifier in selected_ids)
    return ProjectAnalysisReport(
        snapshot_hash=tools.context.input.snapshot_hash,
        investigation_plan=plan,
        investigation_outcomes=tuple(
            InvestigationOutcome(
                id=finding.id,
                investigation_id=finding.investigation_id,
                status=finding.status,
                limitations=finding.limitations,
            )
            for finding in findings
        ),
        investigation_coverage=investigation_coverage(tools, plan, findings),
        retrieved_evidence=tools.retrieved_evidence,
        **content,
    )


def validate_finding(
    tools: RepositoryToolset,
    plan,
    previous,
    finding: InvestigationResult,
    objective,
    current_evidence_ids,
):
    if finding.investigation_id != objective.id:
        raise ValueError("Finding must belong to the active investigation.")
    if any(
        prior.id == finding.id or prior.investigation_id == finding.investigation_id
        for prior in previous
    ):
        raise ValueError("An accepted investigation result cannot be rewritten.")
    content = accepted_content((finding,))
    if finding.status == "completed" and not any(content.values()):
        raise ValueError(
            "Completed investigations require findings or explicit unresolved questions."
        )
    if (
        finding.status == "completed"
        and objective.priority_tier == "project_orientation"
        and not (
            any(
                project.project_id == objective.project_id
                for project in finding.project_identification
            )
            or finding.open_questions
        )
    ):
        raise ValueError(
            "Completed orientation requires project identification or explicit unresolved orientation questions."
        )
    report = assemble_report(tools, plan, (*previous, finding))
    tools.validate_report_access(report)
    # Also check nested fields specific to InvestigationResult, using the same
    # report-local component/integration indexes and plan references.
    local = tools.context._local_indexes(
        (
            report,
            *(
                getattr(finding, name)
                for name in type(finding).model_fields
                if name != "id"
            ),
        )
    )
    tools.context._validate_references(
        finding, local, {record.id for record in (*previous, finding)}
    )
    prior_claims = {
        record.id: record
        for prior in previous
        for record in walk_contracts(prior)
        if isinstance(record, AnalysisClaim)
    }
    source_records = [
        record
        for record in tools.retrieved_evidence
        if record.kind == "source" and record.id in current_evidence_ids
    ]

    def source_backed(claim):
        if claim.status != "supported" or prior_claims.get(claim.id) == claim:
            return
        for identifier in claim.evidence_ids:
            if any(record.id == identifier for record in source_records):
                return
            evidence = tools.context.reference_indexes["snapshot_evidence"].get(
                identifier
            )
            if (
                evidence is not None
                and evidence.start_line is not None
                and any(
                    record.file_id == evidence.file_id
                    and record.start_line <= (evidence.end_line or evidence.start_line)
                    and record.end_line >= evidence.start_line
                    for record in source_records
                )
            ):
                return
        raise ValueError(
            f"Behavioral claim requires inspected source, not metadata alone: {claim.id}"
        )

    for project in finding.project_identification:
        source_backed(project.purpose)
    for component in finding.components:
        source_backed(component.responsibility)
    for flow in finding.flows:
        source_backed(flow.trigger)
        for step in flow.steps:
            source_backed(step.description)
    for relationship in finding.component_relationships:
        if relationship.kind != "imports":
            source_backed(relationship.description)
    for integration in finding.integrations:
        if integration.usage == "verified":
            source_backed(integration.description)
    for testing in finding.testing:
        for observation in testing.observations:
            source_backed(observation)
    for claim in finding.claims:
        source_backed(claim)
    return report


def validate_report(tools, plan, findings, report):
    expected = assemble_report(tools, plan, findings)
    if (
        report.investigation_plan != expected.investigation_plan
        or report.investigation_coverage != expected.investigation_coverage
    ):
        raise ValueError(
            "Report plan and coverage must be derived from execution state."
        )
    if (
        report.investigation_outcomes != expected.investigation_outcomes
        or report.retrieved_evidence != expected.retrieved_evidence
    ):
        raise ValueError(
            "Report outcome and evidence ledgers must match execution state."
        )
    for name in COLLECTION_FIELDS:
        records = {record.id: record for record in getattr(expected, name)}
        actual = {record.id: record for record in getattr(report, name)}
        if actual != records:
            raise ValueError(f"Synthesis cannot add, drop, or rewrite accepted {name}.")
    tools.validate_report_access(report)


def parse_json_contract(text, schema: type[BaseModel], max_characters):
    return schema.model_validate(parse_json_value(text, max_characters))


def parse_json_value(text, max_characters):
    import json

    if not isinstance(text, str) or len(text) > max_characters:
        raise ValueError("Model output must be bounded JSON text.")

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON keys are not permitted.")
            result[key] = value
        return result

    def reject_constant(_value):
        raise ValueError("Nonstandard JSON numeric constants are not permitted.")

    return json.loads(
        text, object_pairs_hook=unique_object, parse_constant=reject_constant
    )


def validation_feedback(error):
    from pydantic import ValidationError

    if isinstance(error, ValidationError):
        return tuple(
            f"{'.'.join(map(str, item['loc'])) or 'response'}: {item['type']}: {item['msg'][:240]}"
            for item in error.errors(include_input=False, include_url=False)[:6]
        )
    return (str(error)[:500],)


def normalize_record_arrays(value, schema):
    """Recover singleton object arrays without modifying facts or primitive fields."""
    definitions = schema.get("$defs", {})

    def visit(item, contract):
        if "$ref" in contract:
            contract = definitions[contract["$ref"].rsplit("/", 1)[1]]
        if "anyOf" in contract:
            contract = next(
                (child for child in contract["anyOf"] if child.get("type") != "null"),
                contract,
            )
            return visit(item, contract) if "anyOf" not in contract else item
        if contract.get("type") == "array":
            child = contract.get("items", {})
            resolved = definitions.get(child.get("$ref", "").rsplit("/", 1)[-1], child)
            if isinstance(item, dict) and resolved.get("type") == "object":
                item = [item]
            return (
                [visit(member, child) for member in item]
                if isinstance(item, list)
                else item
            )
        if isinstance(item, dict):
            properties = contract.get("properties", {})
            return {
                key: visit(member, properties[key]) if key in properties else member
                for key, member in item.items()
            }
        return item

    return visit(value, schema)


def salvage_finding(tools, plan, previous, raw, objective, evidence_ids, reason):
    """Retain independently valid records; rejected records never become claims."""
    from pydantic import TypeAdapter

    from ...services.repository_analysis.context import create_identifier
    from .schemas import OpenQuestion

    base = InvestigationResult(
        id=create_identifier("finding", objective.id),
        investigation_id=objective.id,
        status="incomplete",
        limitations=(reason,),
        open_questions=(
            OpenQuestion(
                id=create_identifier("question", objective.id, "rejected_records"),
                investigation_id=objective.id,
                question=objective.objective,
                reason=reason,
                entity_ids=objective.seed_entity_ids,
            ),
        ),
    )
    if not isinstance(raw, dict):
        return base
    for field in (
        "project_identification",
        "components",
        "integrations",
        "flows",
        "component_relationships",
        "testing",
        "claims",
        "open_questions",
    ):
        values = raw.get(field, [])
        if not isinstance(values, list):
            continue
        for value in values:
            try:
                record = TypeAdapter(
                    InvestigationResult.model_fields[field].annotation
                ).validate_python([value])[0]
                candidate = InvestigationResult.model_validate(
                    base.model_dump() | {field: (*getattr(base, field), record)}
                )
                validate_finding(
                    tools, plan, previous, candidate, objective, evidence_ids
                )
            except ValueError:
                continue
            base = candidate
    return base
