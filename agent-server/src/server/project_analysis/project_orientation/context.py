"""Compact deterministic views and source-reference checks on restricted tools."""

from collections import Counter
from pathlib import Path, PurePosixPath

from server.project_analysis.project_orientation.schemas import Orientation

PROMPTS = Path(__file__).parent / "prompts"


def prompt_template(name):
    return (PROMPTS / f"{name}.md").read_text(encoding="utf-8")


def representation_view(tools):
    snapshot = tools.accessible_snapshot
    incoming = Counter(relation.target_id for relation in snapshot.relationships)
    manifests = {"package.json", "pyproject.toml", "setup.py", "requirements.txt"}
    core = {
        "main",
        "app",
        "applications",
        "__init__",
        "index",
        "page",
        "routes",
        "views",
    }
    entry_files = {entry.file_id for entry in snapshot.entrypoints if entry.file_id}

    def rank(source):
        path = PurePosixPath(source.path)
        sample = any(
            part in {"tests", "test", "examples", "fixtures", "docs_src"}
            for part in path.parts
        )
        return (
            sample,
            path.name not in manifests,
            path.stem not in core,
            source.id not in entry_files,
            -incoming[source.id],
            source.path,
        )

    selected = []
    for project in snapshot.projects[:8]:
        selected.extend(
            sorted(
                (
                    source
                    for source in snapshot.files
                    if source.project_id == project.id
                ),
                key=rank,
            )[:4]
        )
    selected = selected[:16]
    return {
        "snapshot_hash": snapshot.repository.snapshot_hash,
        "repository_name": snapshot.repository.name,
        "projects": [
            {"id": project.id, "path": project.path, "name": project.name}
            for project in snapshot.projects[:8]
        ],
        "technologies": [
            {"name": record.name, "kind": record.kind, "detection": record.detection}
            for record in snapshot.technologies[:20]
        ],
        "technical_file_count": len(snapshot.files),
        "candidate_files": [
            {"id": source.id, "path": source.path, "line_count": source.line_count}
            for source in selected
        ],
        "entrypoints": [
            {"kind": entry.kind, "target": entry.target, "file_id": entry.file_id}
            for entry in snapshot.entrypoints[:12]
        ],
        "omissions": {
            "projects": max(0, len(snapshot.projects) - 8),
            "candidate_files": len(snapshot.files) - len(selected),
            "entrypoints": max(0, len(snapshot.entrypoints) - 12),
            "technologies": max(0, len(snapshot.technologies) - 20),
        },
        "limitations": [
            "File roles and import relationships prioritize inspection; they do not prove functionality.",
            "Narrative documentation is excluded. This orientation is not exhaustive.",
        ],
    }


def validate_orientation(tools, orientation):
    files = {source.id: source for source in tools.accessible_snapshot.files}
    evidence = {
        record.id: record
        for record in tools.retrieved_evidence
        if record.kind == "source"
    }
    observations = [orientation.project_type, orientation.purpose]
    for component in orientation.components:
        if any(identifier not in files for identifier in component.file_ids):
            raise ValueError(
                "Component file_ids must refer to accessible snapshot files."
            )
        if component.responsibility.status == "supported" and not any(
            evidence.get(identifier)
            and evidence[identifier].file_id in component.file_ids
            for identifier in component.responsibility.evidence_ids
        ):
            raise ValueError(
                "Component responsibility must cite inspected source in its file_ids."
            )
        observations.append(component.responsibility)
    for point in orientation.starting_points:
        if point.file_id not in files:
            raise ValueError("Starting points must refer to accessible snapshot files.")
    for observation in observations:
        if observation and any(
            identifier not in evidence for identifier in observation.evidence_ids
        ):
            raise ValueError(
                "Use only source evidence IDs delivered by this run's tools."
            )


def retain_valid_sections(tools, raw):
    """Preserve independently valid sections without changing their statements."""
    if not isinstance(raw, dict):
        return None
    result = Orientation()
    for field in (
        "project_type",
        "purpose",
        "components",
        "starting_points",
        "uncertainties",
    ):
        values = raw.get(field)
        if values is None:
            continue
        members = (
            values
            if field in {"components", "starting_points", "uncertainties"}
            and isinstance(values, list)
            else [values]
        )
        for member in members:
            value = (
                (*getattr(result, field), member)
                if field in {"components", "starting_points", "uncertainties"}
                else member
            )
            try:
                candidate = Orientation.model_validate(
                    result.model_dump() | {field: value}
                )
                validate_orientation(tools, candidate)
            except ValueError:
                continue
            result = candidate
    return (
        result if result.project_type or result.purpose or result.components else None
    )
