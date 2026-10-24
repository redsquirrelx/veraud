"""Balanced application candidates and connected architectural navigation hints."""

from pathlib import PurePosixPath

from ..project_orientation.context import representation_view as orientation_view
from .coverage import application_files
from .discovery import connected_candidates

ROLES = {
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


def relationship_signals(snapshot, selected, files):
    owners = {symbol.id: symbol.file_id for symbol in snapshot.symbols}

    def owner(identifier):
        return owners.get(identifier, identifier)

    relationships = [
        relation
        for relation in snapshot.relationships
        if owner(relation.source_id) in selected
        or owner(relation.target_id) in selected
    ]
    relationships.sort(
        key=lambda relation: (
            relation.resolution != "internal",
            relation.kind not in {"from_import", "import", "inherits"},
            not (
                owner(relation.source_id) in selected
                and owner(relation.target_id) in selected
            ),
            relation.source_id,
            relation.target_id or "",
            relation.kind,
        )
    )
    signals = [
        {
            "source_id": relation.source_id,
            "target_id": relation.target_id,
            "kind": relation.kind,
            "resolution": relation.resolution,
            "source_path": files[owner(relation.source_id)].path
            if owner(relation.source_id) in files
            else None,
            "target_path": files[owner(relation.target_id)].path
            if owner(relation.target_id) in files
            else None,
        }
        for relation in relationships[:16]
    ]
    return signals, max(0, len(relationships) - 16)


def representation_view(tools, orientation=None):
    view = orientation_view(tools)
    snapshot = tools.accessible_snapshot
    files = {source.id: source for source in snapshot.files}
    per_project = application_files(tools)
    bundles, filename_roles = connected_candidates(snapshot, per_project)
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
    ordered = sorted(
        snapshot.files,
        key=lambda source: (
            PurePosixPath(source.path).stem == "__init__",
            (source.line_count or 0) <= 3,
            source.path,
        ),
    )
    candidates = []
    used_areas = set()
    for source in ordered:
        path = PurePosixPath(source.path)
        matches = [part for part in path.parts if part in ROLES]
        role = filename_roles.get(source.id) or (matches[-1] if matches else None)
        if role and not any(
            part in {"tests", "test", "docs_src", "examples"} for part in path.parts
        ):
            area = (source.project_id, role)
            if area not in used_areas:
                used_areas.add(area)
                candidates.append(source)
    selected = {}
    # Reserve two candidates per application before adding role and bundle hints.
    for sources in per_project.values():
        ranked = sorted(
            sources,
            key=lambda source: (
                PurePosixPath(source.path).stem
                not in {"main", "app", "App", "page", "router", "routes"},
                (source.line_count or 0) <= 3,
                filename_roles.get(source.id) is None,
                "/shared/ui-kit/" in source.path,
                source.path,
            ),
        )
        for source in ranked[:2]:
            selected.setdefault(source.id, source)
    for bundle in bundles:
        for item in bundle["files"]:
            if len(selected) < 20:
                selected.setdefault(item["file_id"], files[item["file_id"]])
    for source in candidates[:10]:
        if len(selected) < 20:
            selected.setdefault(source.id, source)
    for item in view["candidate_files"]:
        if len(selected) < 16 and not PurePosixPath(
            files[item["id"]].path
        ).name.startswith("."):
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
    view["investigation_bundles"] = bundles
    view["application_targets"] = [
        {
            "project_id": project.id,
            "path": project.path,
            "candidate_paths": [
                source.path
                for source in selected.values()
                if source.project_id == project.id
            ],
        }
        for project in snapshot.projects
        if project.id in per_project
    ]
    view["relationship_signals"], omitted = relationship_signals(
        snapshot, selected, files
    )
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
        relationships=omitted, infrastructure=max(0, len(snapshot.infrastructure) - 8)
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
