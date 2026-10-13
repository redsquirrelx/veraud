"""Implementation-bearing application scope and evidence-backed coverage depth."""

from pathlib import PurePosixPath


class EvidenceGap(ValueError):
    """A source investigation can address this validation failure."""


def application_files(tools):
    result = {}
    extensions = {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".vue",
        ".svelte",
        ".go",
        ".java",
        ".cs",
        ".rs",
        ".rb",
        ".php",
        ".kt",
        ".swift",
    }
    for source in tools.accessible_snapshot.files:
        path = PurePosixPath(source.path)
        if path.suffix.lower() not in extensions:
            continue
        if (
            any(
                part in {"tests", "test", "fixtures", "examples", "docs_src"}
                for part in path.parts
            )
            or any(marker in path.name for marker in (".test.", ".spec.", ".config."))
            or path.name.startswith(("test_", "."))
        ):
            continue
        result.setdefault(source.project_id, []).append(source)
    return result


def application_coverage(tools, report):
    evidence = {
        record.id: record.file_id
        for record in tools.retrieved_evidence
        if record.kind == "source"
    }
    inspected = set(evidence.values())
    projects = {project.id: project for project in tools.accessible_snapshot.projects}
    result = []
    for project_id, sources in application_files(tools).items():
        ids = {source.id for source in sources}
        units = (
            [unit for unit in report.organization if ids.intersection(unit.file_ids)]
            if report
            else []
        )
        cited = {
            evidence[identifier]
            for unit in units
            if unit.responsibility.status == "supported"
            for identifier in unit.responsibility.evidence_ids
            if evidence.get(identifier) in ids
        }
        explained = len(cited) >= min(2, len(ids))
        status = (
            "explained"
            if explained
            else "inspected"
            if ids.intersection(inspected)
            else "uninspected"
        )
        result.append(
            {
                "project_id": project_id,
                "path": projects[project_id].path,
                "status": status,
                "inspected_file_ids": sorted(ids.intersection(inspected)),
                "reason": "Supported responsibilities cite representative implementation files."
                if explained
                else "Responsibilities need supported evidence from at least two implementation files when available."
                if status == "inspected"
                else "No implementation source was inspected for this application.",
            }
        )
    return result


def validate_closure(tools, report):
    if report.closest_architecture is None or report.explanation is None:
        raise EvidenceGap(
            "Architecture closure requires closest_architecture and explanation, including explicit hypothesis/unresolved conclusions when evidence is insufficient."
        )
    targets = application_files(tools)
    coverage = application_coverage(tools, report)
    missing = []
    shallow = []
    for item in coverage:
        ids = {source.id for source in targets[item["project_id"]]}
        units = [
            unit for unit in report.organization if ids.intersection(unit.file_ids)
        ]
        if not units:
            missing.append(item["path"])
        if item["status"] != "explained" and not any(
            unit.responsibility.status != "supported" for unit in units
        ):
            shallow.append(item["path"])
    if missing:
        raise EvidenceGap(
            f"Applications lack architectural responsibilities: {missing}. Inspect their implementation or declare a scoped hypothesis/unresolved unit with limitations."
        )
    if shallow:
        raise EvidenceGap(
            f"Applications have insufficient implementation depth: {shallow}. Cite responsibilities from two implementation files per application when available; follow a concrete internal connection or mark the responsibility hypothetical with limitations."
        )
