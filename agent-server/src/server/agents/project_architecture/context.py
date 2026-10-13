"""Architectural source-reference validation, alias normalization, and salvage."""

from copy import deepcopy
from itertools import pairwise
from pathlib import Path, PurePosixPath

from ..repository_runtime.context import walk_contracts
from .coverage import EvidenceGap
from .schemas import (
    ArchitecturalClaim,
    ArchitectureClassification,
    ArchitectureReport,
    SourceCitation,
)

PROMPTS = Path(__file__).parent / "prompts"


def prompt_template(name):
    return (PROMPTS / f"{name}.md").read_text(encoding="utf-8")


def contract_view(schema):
    """Readable compact type grammar; full contracts still validate responses."""

    def shape(value):
        if "$ref" in value:
            return value["$ref"].rsplit("/", 1)[1]
        if "enum" in value:
            return "|".join(map(str, value["enum"]))
        if "anyOf" in value:
            return "|".join(shape(child) for child in value["anyOf"])
        if value.get("type") == "array":
            return "[" + shape(value.get("items", {})) + "]"
        return value.get("type", "any")

    def fields(value):
        return {
            "required": value.get("required", []),
            "fields": {
                key: shape(child)
                for key, child in value.get("properties", {}).items()
                if key != "assessment_origin"
            },
        }

    return {
        "response_fields": fields(schema),
        "types": {
            name: fields(value) for name, value in schema.get("$defs", {}).items()
        },
        "rules": "Return tool_calls OR architecture as the top-level key. [Type] means a JSON array, not one object. No extra fields. Claims are objects, never strings. Supported classifications additionally require observed_paths OR observed_dependencies, contrast_question (string), contrast_result (supported claim). Copy actual evidence IDs from the source ledger; do not invent identifiers. Omit unused optional fields.",
    }


def validate_orientation_input(tools, orientation):
    if orientation is None:
        return
    tools.context.require_snapshot(orientation.snapshot_hash)
    # Orientation is guidance only: its citations never become architect evidence.
    files = {source.id: source for source in tools.accessible_snapshot.files}
    if orientation.orientation:
        identifiers = [
            point.file_id for point in orientation.orientation.starting_points
        ]
        identifiers.extend(
            identifier
            for component in orientation.orientation.components
            for identifier in component.file_ids
        )
        if any(identifier not in files for identifier in identifiers):
            raise ValueError("Orientation references inaccessible files.")
    for record in orientation.retrieved_evidence:
        if (
            record.snapshot_hash != tools.context.input.snapshot_hash
            or record.file_id not in files
            or record.content_hash != files[record.file_id].content_hash
        ):
            raise ValueError(
                "Orientation evidence must match accessible snapshot source hashes."
            )


def connection_evidence_ids(tools, report, connection):
    identifiers = set(connection.description.evidence_ids)
    if connection not in report.connections:
        # Classification graphs can reference an already described connection;
        # duplicating the same endpoint citation list is not additional evidence.
        for described in report.connections:
            if described.description.status == "supported" and (
                described.source_unit,
                described.target_unit,
            ) == (connection.source_unit, connection.target_unit):
                identifiers.update(described.description.evidence_ids)
    endpoints = {
        unit.name: unit
        for unit in report.organization
        if unit.name in {connection.source_unit, connection.target_unit}
    }
    if len(endpoints) == 2 and all(
        unit.responsibility.status == "supported" for unit in endpoints.values()
    ):
        records = {
            record.id: record
            for record in tools.retrieved_evidence
            if record.kind == "source"
        }
        origin = endpoints[connection.source_unit]
        target = endpoints[connection.target_unit]
        owners = {
            symbol.id: symbol.file_id for symbol in tools.accessible_snapshot.symbols
        }
        # Endpoint responsibility citations may be reused only for an actual,
        # resolved structural dependency, never for a guessed runtime connection.
        linked = {
            (
                owners.get(relation.source_id, relation.source_id),
                owners.get(relation.target_id, relation.target_id),
            )
            for relation in tools.accessible_snapshot.relationships
            if relation.resolution == "internal"
            and relation.kind in {"import", "from_import", "inherits", "implements"}
            and owners.get(relation.source_id, relation.source_id) in origin.file_ids
            and owners.get(relation.target_id, relation.target_id) in target.file_ids
        }
        cited = {
            records[identifier].file_id
            for identifier in identifiers
            if identifier in records
        }
        for origin_file, target_file in linked:
            if not cited.intersection({origin_file, target_file}):
                continue
            for unit, file_id in ((origin, origin_file), (target, target_file)):
                identifiers.update(
                    identifier
                    for identifier in unit.responsibility.evidence_ids
                    if identifier in records and records[identifier].file_id == file_id
                )
    return identifiers


def normalize_source_references(tools, raw):
    """Resolve file-shaped citation aliases only to one actually inspected range."""
    records = {}
    known = set()
    for record in tools.retrieved_evidence:
        if record.kind == "source":
            records.setdefault(record.file_id, set()).add(record.id)
            known.add(record.id)
    aliases = {}
    for file_id, identifiers in records.items():
        if len(identifiers) == 1:
            identifier = next(iter(identifiers))
            aliases[file_id] = identifier
            aliases["retrieval:" + file_id.removeprefix("file:")] = identifier
    result = deepcopy(raw)
    repairs = {}

    def visit(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "evidence_ids" and isinstance(child, list):
                    for index, identifier in enumerate(child):
                        if (
                            isinstance(identifier, str)
                            and identifier not in known
                            and identifier in aliases
                        ):
                            child[index] = aliases[identifier]
                            repairs[identifier] = aliases[identifier]
                else:
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(result)
    return result, repairs


def validate_report(tools, report):
    files = {source.id: source for source in tools.accessible_snapshot.files}
    source = {
        record.id: record
        for record in tools.retrieved_evidence
        if record.kind == "source"
    }
    for claim in walk_contracts(report):
        if isinstance(claim, ArchitecturalClaim) and any(
            identifier not in source for identifier in claim.evidence_ids
        ):
            invalid = [
                identifier
                for identifier in claim.evidence_ids
                if identifier not in source
            ]
            raise ValueError(
                f"Claim {claim.statement[:80]!r} cites unavailable source IDs {invalid[:4]}. Copy IDs from this inspected-source map: "
                + str(
                    {
                        files[record.file_id].path: identifier
                        for identifier, record in source.items()
                    }
                )
            )
    names = [unit.name for unit in report.organization]
    if len(names) != len(set(names)):
        raise ValueError("Organization unit names must be unique.")
    for unit in report.organization:
        if any(identifier not in files for identifier in unit.file_ids):
            raise ValueError("Organization file_ids must be accessible snapshot files.")
        if unit.responsibility.status == "supported" and not any(
            source[identifier].file_id in unit.file_ids
            for identifier in unit.responsibility.evidence_ids
        ):
            raise ValueError("Unit responsibility must cite its own file_ids.")
    classification = report.closest_architecture
    paths = classification.observed_paths if classification else ()
    for path in paths:
        for previous, following in pairwise(path):
            if previous.target_unit != following.source_unit:
                raise ValueError(
                    "Observed path connections must form a continuous responsibility chain."
                )
    dependencies = classification.observed_dependencies if classification else ()
    for connection in (
        *report.connections,
        *(edge for path in paths for edge in path),
        *dependencies,
    ):
        if connection.source_unit == connection.target_unit:
            raise ValueError(
                "Architectural connections must join different responsibilities."
            )
        if connection.source_unit not in names or connection.target_unit not in names:
            raise ValueError(
                f"Connections must reference declared organization units {names}; got {connection.source_unit!r} -> {connection.target_unit!r}."
            )
        if (
            connection.description.status == "supported"
            and len(
                {
                    source[identifier].file_id
                    for identifier in connection_evidence_ids(tools, report, connection)
                }
            )
            < 2
        ):
            raise EvidenceGap(
                f"Supported cross-unit connections require source from both responsibilities: {connection.source_unit} -> {connection.target_unit}. "
                + "Available endpoint evidence: "
                + str(
                    {
                        unit.name: unit.responsibility.evidence_ids
                        for unit in report.organization
                        if unit.name in {connection.source_unit, connection.target_unit}
                    }
                )
            )
        if connection.description.status == "supported":
            referenced = {
                source[identifier].file_id
                for identifier in connection_evidence_ids(tools, report, connection)
            }
            if any(
                not referenced.intersection(unit.file_ids)
                for unit in report.organization
                if unit.name in {connection.source_unit, connection.target_unit}
            ):
                raise EvidenceGap(
                    "Connection evidence must include its source and target units."
                )
    if (
        report.closest_architecture
        and report.closest_architecture.assessment.status == "supported"
    ):
        if dependencies:
            reached = {dependencies[0].source_unit}
            nodes = {
                name
                for edge in dependencies
                for name in (edge.source_unit, edge.target_unit)
            }
            while True:
                expanded = reached | {
                    name
                    for edge in dependencies
                    if reached.intersection({edge.source_unit, edge.target_unit})
                    for name in (edge.source_unit, edge.target_unit)
                }
                if expanded == reached:
                    break
                reached = expanded
            if reached != nodes:
                raise EvidenceGap(
                    "Observed dependency links must form a connected responsibility graph."
                )
        cited = {
            source[identifier].file_id
            for identifier in report.closest_architecture.assessment.evidence_ids
        }
        if (
            len(cited) < 2
            or len(
                [
                    unit
                    for unit in report.organization
                    if cited.intersection(unit.file_ids)
                ]
            )
            < 2
        ):
            raise EvidenceGap(
                "Supported pattern classification requires multiple files across at least two observed responsibilities."
            )
        path_files = [
            {
                source[identifier].file_id
                for edge in path
                for identifier in connection_evidence_ids(tools, report, edge)
            }
            for path in (*paths, dependencies)
            if path
        ]
        if not cited.intersection(set().union(*path_files)):
            raise ValueError(
                "Pattern assessment must cite its observed implementation path."
            )
        if classification.scope_kind == "repository" and path_files[0] == path_files[1]:
            raise ValueError(
                "Repository-wide paths must inspect different implementation files, not repeat the same evidence."
            )
    for item in report.infrastructure:
        if item.inspected_use and item.inspected_use.status == "supported":
            paths = [
                files[source[identifier].file_id].path
                for identifier in item.inspected_use.evidence_ids
            ]
            if not any(
                PurePosixPath(path).suffix.casefold()
                in {
                    ".py",
                    ".js",
                    ".jsx",
                    ".ts",
                    ".tsx",
                    ".go",
                    ".java",
                    ".cs",
                    ".rs",
                    ".rb",
                    ".php",
                    ".sh",
                    ".c",
                    ".cpp",
                    ".h",
                    ".kt",
                    ".swift",
                    ".scala",
                    ".ex",
                    ".exs",
                    ".lua",
                }
                for path in paths
            ):
                raise ValueError(
                    "Supported infrastructure use requires implementation source, not only configuration."
                )


def retain_valid_sections(tools, raw):
    if not isinstance(raw, dict):
        return None
    result = ArchitectureReport()
    for field in (
        "organization",
        "connections",
        "closest_architecture",
        "supporting_evidence",
        "deviations",
        "infrastructure",
        "explanation",
        "uncertainties",
    ):
        values = raw.get(field)
        if values is None:
            continue
        collection = field not in {"closest_architecture", "explanation"}
        for member in values if collection and isinstance(values, list) else [values]:
            value = (*getattr(result, field), member) if collection else member
            if field == "closest_architecture" and isinstance(value, dict):
                value = value | {"assessment_origin": "model"}
            try:
                candidate = ArchitectureReport.model_validate(
                    result.model_dump() | {field: value}
                )
                validate_report(tools, candidate)
            except ValueError as error:
                if field == "closest_architecture" and isinstance(member, dict):
                    try:
                        assessment = ArchitecturalClaim.model_validate(
                            member.get("assessment")
                        )
                        if assessment.status != "supported":
                            continue
                        downgraded = ArchitectureClassification(
                            pattern=member.get("pattern"),
                            assessment_origin="host_downgrade",
                            scope_kind=member.get("scope_kind", "local"),
                            assessment=assessment.model_copy(
                                update={
                                    "status": "hypothesis",
                                    "limitations": (
                                        *assessment.limitations,
                                        "Host retained the model's proposed pattern as a hypothesis because its support failed validation: "
                                        + str(error)[:500],
                                    ),
                                }
                            ),
                        )
                        candidate = ArchitectureReport.model_validate(
                            result.model_dump() | {field: downgraded}
                        )
                        validate_report(tools, candidate)
                    except ValueError:
                        continue
                    result = candidate
                continue
            result = candidate
    if not (result.organization or result.closest_architecture or result.explanation):
        return None
    if result.closest_architecture is None:
        result = result.model_copy(
            update={
                "closest_architecture": ArchitectureClassification(
                    pattern="No clear pattern established",
                    assessment_origin="host_fallback",
                    assessment=ArchitecturalClaim(
                        statement="No valid architectural pattern assessment was retained.",
                        scope="Accepted inspected findings",
                        status="unresolved",
                        limitations=(
                            "Host fallback: the model omitted the classification or its assessment failed validation.",
                        ),
                    ),
                )
            }
        )
    if result.explanation is None:
        result = result.model_copy(
            update={
                "explanation": ArchitecturalClaim(
                    statement="A consolidated architectural explanation was not established.",
                    scope="Accepted inspected findings",
                    status="unresolved",
                    limitations=(
                        "Host fallback: the model omitted the explanation or it failed source validation.",
                    ),
                )
            }
        )
    return result


def citations_for(tools, report):
    files = {source.id: source for source in tools.accessible_snapshot.files}
    cited = {
        identifier
        for claim in walk_contracts(report)
        if isinstance(claim, ArchitecturalClaim)
        for identifier in claim.evidence_ids
    }
    return tuple(
        SourceCitation(
            evidence_id=record.id,
            file_id=record.file_id,
            path=files[record.file_id].path,
            start_line=record.start_line,
            end_line=record.end_line,
            content_hash=record.content_hash,
        )
        for record in tools.retrieved_evidence
        if record.kind == "source" and record.id in cited
    )
