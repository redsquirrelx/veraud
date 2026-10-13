"""Deterministic claim selection and independently delivered evidence validation."""

import hashlib
import json

from ..project_architecture.diagram import diagram_interpretations
from ..project_architecture.schemas import ArchitecturalClaim, SourceCitation
from ..repository_runtime.access import repository_relative_path
from ..repository_runtime.context import walk_contracts
from ..repository_runtime.responses import validation_feedback
from .schemas import ReviewTarget, SemanticFinding


def report_hash(original):
    text = json.dumps(
        original.architecture.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(text.encode()).hexdigest()


def validate_input(tools, original):
    tools.context.require_snapshot(original.snapshot_hash)
    if original.architecture is None:
        raise ValueError("Semantic validation requires an architectural report.")
    if tools.budget_usage.tool_calls or tools.retrieved_evidence:
        raise ValueError(
            "Semantic validation requires a fresh, independent tool ledger."
        )
    files = {source.id: source for source in tools.accessible_snapshot.files}
    records = {record.id: record for record in original.retrieved_evidence}
    for record in records.values():
        source = files.get(record.file_id)
        if (
            source is None
            or record.snapshot_hash != original.snapshot_hash
            or record.content_hash != source.content_hash
            or (record.kind == "source" and record.end_line > (source.line_count or 0))
        ):
            raise ValueError(
                "Architectural evidence must match accessible retained source."
            )
    for contract in walk_contracts(original.architecture):
        if isinstance(contract, ArchitecturalClaim) and any(
            identifier not in records or records[identifier].kind != "source"
            for identifier in contract.evidence_ids
        ):
            raise ValueError(
                "Architectural claims reference unavailable source evidence."
            )
        if any(
            identifier not in files for identifier in getattr(contract, "file_ids", ())
        ):
            raise ValueError("Architectural units reference inaccessible files.")


def review_targets(tools, original):
    """JSON pointers remain stable for this hashed report, including nested links."""
    files = {source.id: source for source in tools.accessible_snapshot.files}
    records = {record.id: record for record in original.retrieved_evidence}
    targets = []

    def add(pointer, kind, claim, context):
        if claim is None:
            return
        hints = tuple(
            SourceCitation(
                evidence_id=record.id,
                file_id=record.file_id,
                path=files[record.file_id].path,
                start_line=record.start_line,
                end_line=record.end_line,
                content_hash=record.content_hash,
            )
            for identifier in claim.evidence_ids
            if (record := records.get(identifier)) and record.kind == "source"
        )
        targets.append(
            ReviewTarget(
                id=pointer, kind=kind, claim=claim, context=context, source_hints=hints
            )
        )

    report = original.architecture
    classification = report.closest_architecture
    if classification:
        details = {
            "pattern": classification.pattern,
            "scope_kind": classification.scope_kind,
            "contrast_question": classification.contrast_question,
            "assessment_origin": classification.assessment_origin,
            "units": [
                {
                    "name": unit.name,
                    "paths": [files[identifier].path for identifier in unit.file_ids],
                    "responsibility": unit.responsibility.statement,
                }
                for unit in report.organization
            ],
            "dependency_links": [
                {
                    "source": edge.source_unit,
                    "target": edge.target_unit,
                    "statement": edge.description.statement,
                }
                for path in (
                    *classification.observed_paths,
                    classification.observed_dependencies,
                )
                for edge in path
            ],
        }
        add(
            "/closest_architecture/assessment",
            "classification",
            classification.assessment,
            details,
        )
    for index, unit in enumerate(report.organization):
        add(
            f"/organization/{index}/responsibility",
            "responsibility",
            unit.responsibility,
            {
                "unit": unit.name,
                "paths": [files[identifier].path for identifier in unit.file_ids],
            },
        )

    def connection(pointer, edge):
        add(
            pointer + "/description",
            "connection",
            edge.description,
            {"source_unit": edge.source_unit, "target_unit": edge.target_unit},
        )

    for index, edge in enumerate(report.connections):
        connection(f"/connections/{index}", edge)
    add("/explanation", "explanation", report.explanation, {})
    if classification:
        add(
            "/closest_architecture/contrast_result",
            "contrast",
            classification.contrast_result,
            details,
        )
        for index, edge in enumerate(classification.observed_dependencies):
            connection(f"/closest_architecture/observed_dependencies/{index}", edge)
        for index, path in enumerate(classification.observed_paths):
            for step, edge in enumerate(path):
                connection(f"/closest_architecture/observed_paths/{index}/{step}", edge)
    for index, claim in enumerate(report.supporting_evidence):
        add(f"/supporting_evidence/{index}", "supporting_decision", claim, {})
    for index, item in enumerate(report.deviations):
        add(
            f"/deviations/{index}/observed_decision",
            "deviation",
            item.observed_decision,
            {
                "pattern_expectation": item.pattern_expectation,
                "explanation": item.explanation,
            },
        )
    for index, item in enumerate(report.infrastructure):
        for field in ("configured", "inspected_use"):
            add(
                f"/infrastructure/{index}/{field}",
                "infrastructure",
                getattr(item, field),
                {"name": item.name, "kind": item.kind},
            )
    for interpretation in diagram_interpretations(report):
        add(
            interpretation.pointer,
            interpretation.kind,
            interpretation.claim,
            interpretation.context,
        )
    return tuple(targets)


def target_was_inspected(target, records):
    return any(
        record.kind == "source"
        and record.file_id == hint.file_id
        and record.start_line <= hint.end_line
        and hint.start_line <= record.end_line
        for hint in target.source_hints
        for record in records
    )


def validate_finding(tools, finding, selected):
    if finding.target_id not in selected:
        raise ValueError("Finding target must be an offered JSON pointer.")
    if finding.checked_statement != selected[finding.target_id].claim.statement:
        raise ValueError(
            "checked_statement must exactly match the original claim at target_id; do not review a different assertion."
        )
    records = {
        record.id: record
        for record in tools.retrieved_evidence
        if record.kind == "source"
    }
    cited = (
        *finding.evidence_ids,
        *(finding.correction.evidence_ids if finding.correction else ()),
    )
    if any(identifier not in records for identifier in cited):
        raise ValueError(
            "Verdict/correction cites source not inspected by this validator."
        )
    target = selected[finding.target_id]
    if target.source_hints and not target_was_inspected(target, records.values()):
        raise ValueError(
            f"Independently inspect the claim's cited source before closing it: {[hint.path for hint in target.source_hints]}."
        )
    paths = {source.path for source in tools.accessible_snapshot.files}
    for request in finding.missing_evidence:
        if any(repository_relative_path(path) not in paths for path in request.paths):
            raise ValueError(
                "Evidence requests must reference accessible technical files."
            )


def retain_findings(tools, raw, selected):
    accepted, errors = {}, []
    for item in raw:
        try:
            finding = SemanticFinding.model_validate(item)
            validate_finding(tools, finding, selected)
            if finding.target_id in accepted:
                raise ValueError("Duplicate finding target.")
            accepted[finding.target_id] = finding
        except ValueError as error:
            errors.extend(validation_feedback(error))
    return accepted, tuple(errors[:4])
