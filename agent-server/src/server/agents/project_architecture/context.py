"""Architecture candidate projection, scope checks, and verifiable source citations."""

from pathlib import Path, PurePosixPath

from ..project_analysis.context import walk_contracts
from ..project_orientation.context import representation_view as orientation_view
from .schemas import ArchitecturalClaim, ArchitectureReport, SourceCitation

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
                key: shape(child) for key, child in value.get("properties", {}).items()
            },
        }

    return {
        "response_fields": fields(schema),
        "types": {
            name: fields(value) for name, value in schema.get("$defs", {}).items()
        },
        "rules": "Return tool_calls OR architecture as the top-level key. [Type] means a JSON array, not one object. No extra fields. Claims are objects, never strings. Omit unused optional fields.",
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


def representation_view(tools, orientation=None):
    view = orientation_view(tools)
    snapshot = tools.accessible_snapshot
    files = {source.id: source for source in snapshot.files}
    roles = {
        "controller",
        "controllers",
        "view",
        "views",
        "route",
        "routes",
        "service",
        "services",
        "repository",
        "repositories",
        "domain",
        "application",
        "infrastructure",
        "model",
        "models",
        "database",
        "adapters",
        "ports",
    }
    symbols = {identifier: [] for identifier in files}
    for symbol in snapshot.symbols:
        if len(symbols[symbol.file_id]) < 2 and symbol.parent_symbol_id is None:
            symbols[symbol.file_id].append(
                {
                    "name": symbol.name,
                    "start_line": symbol.start_line,
                    "end_line": symbol.end_line,
                }
            )
    candidates = []
    used_areas = set()
    ordered = sorted(
        snapshot.files,
        key=lambda source: (
            PurePosixPath(source.path).stem == "__init__",
            (source.line_count or 0) <= 3,
            source.path,
        ),
    )
    for source in ordered:
        path = PurePosixPath(source.path)
        matches = [part for part in path.parts if part in roles]
        if matches and not any(
            part in {"tests", "test", "docs_src", "examples"} for part in path.parts
        ):
            role = matches[-1]
            if role not in used_areas:
                used_areas.add(role)
                candidates.append(source)
    selected = {source.id: source for source in candidates[:10]}
    for item in view["candidate_files"]:
        if len(selected) < 16:
            selected.setdefault(item["id"], files[item["id"]])
    if orientation and orientation.orientation:
        for point in orientation.orientation.starting_points[:4]:
            selected.setdefault(point.file_id, files[point.file_id])
    selected = dict(list(selected.items())[:20])
    view["candidate_files"] = [
        {
            "id": source.id,
            "path": source.path,
            "line_count": source.line_count,
            "symbols": symbols[source.id],
        }
        for source in selected.values()
    ]
    view["omissions"]["candidate_files"] = len(files) - len(selected)
    relationships = [
        relation
        for relation in snapshot.relationships
        if relation.source_id in selected or relation.target_id in selected
    ]
    view["relationship_signals"] = [
        {
            "source_id": relation.source_id,
            "target_id": relation.target_id,
            "kind": relation.kind,
            "resolution": relation.resolution,
        }
        for relation in relationships[:16]
    ]
    view["infrastructure_signals"] = [
        {
            "name": item.name,
            "kind": item.kind,
            "detection": item.detection,
            "evidence_ids": item.evidence_ids[:2],
        }
        for item in snapshot.infrastructure[:8]
    ]
    view["configuration_files"] = [
        {"id": source.id, "path": source.path}
        for source in ordered
        if PurePosixPath(source.path)
        .name.casefold()
        .startswith(("dockerfile", "docker-compose", "compose."))
    ][:8]
    view["omissions"].update(
        relationships=max(0, len(relationships) - 16),
        infrastructure=max(0, len(snapshot.infrastructure) - 8),
    )
    view["orientation_guidance"] = None
    if orientation and orientation.orientation:
        value = orientation.orientation
        view["orientation_guidance"] = {
            "purpose": value.purpose.statement if value.purpose else None,
            "components": [
                {
                    "name": item.name,
                    "file_ids": item.file_ids,
                    "responsibility": item.responsibility.statement,
                }
                for item in value.components
            ],
            "uncertainties": value.uncertainties,
            "status": orientation.completion_status,
            "instruction": "Unverified guidance; retrieve architect source before relying on a claim.",
        }
    return view


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
            raise ValueError(
                "Cite only source evidence delivered during the architect's own investigation."
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
    for connection in report.connections:
        if connection.source_unit not in names or connection.target_unit not in names:
            raise ValueError(
                f"Connections must reference declared organization units {names}; got {connection.source_unit!r} -> {connection.target_unit!r}."
            )
        if (
            connection.description.status == "supported"
            and len(
                {
                    source[identifier].file_id
                    for identifier in connection.description.evidence_ids
                }
            )
            < 2
        ):
            raise ValueError(
                "Supported cross-unit connections require source from both responsibilities."
            )
        if connection.description.status == "supported":
            referenced = {
                source[identifier].file_id
                for identifier in connection.description.evidence_ids
            }
            if any(
                not referenced.intersection(unit.file_ids)
                for unit in report.organization
                if unit.name in {connection.source_unit, connection.target_unit}
            ):
                raise ValueError(
                    "Connection evidence must include its source and target units."
                )
    if (
        report.closest_architecture
        and report.closest_architecture.assessment.status == "supported"
    ):
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
            raise ValueError(
                "Supported pattern classification requires multiple files across at least two observed responsibilities."
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
            try:
                candidate = ArchitectureReport.model_validate(
                    result.model_dump() | {field: value}
                )
                validate_report(tools, candidate)
            except ValueError:
                continue
            result = candidate
    return (
        result
        if result.organization or result.closest_architecture or result.explanation
        else None
    )


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
