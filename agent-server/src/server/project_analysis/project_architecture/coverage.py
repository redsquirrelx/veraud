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


def relationship_recovery_tasks(tools, report, actions):
    """Queue unread endpoints and a caller/composition search per pending unit."""
    if report is None:
        return []
    files = {source.id: source for source in tools.accessible_snapshot.files}
    paths = {source.path for source in files.values()}
    inspected = {
        record.file_id for record in tools.retrieved_evidence if record.kind == "source"
    }
    units = {unit.name: unit for unit in report.organization}
    tasks, scheduled = [], set()
    for item in relationship_coverage(tools, report):
        if item["status"] not in {"unresolved", "uninvestigated"}:
            continue
        unit = units[item["unit_name"]]
        candidates = list(
            dict.fromkeys(
                [
                    *item["pending_paths"],
                    *(
                        files[file_id].path
                        for file_id in unit.file_ids
                        if file_id in files
                    ),
                ]
            )
        )
        for path in candidates:
            key = "read:" + path
            if path not in paths or key in actions or key in scheduled:
                continue
            source = next(source for source in files.values() if source.path == path)
            if source.id in inspected:
                continue
            tasks.append(
                {
                    "key": key,
                    "unit": unit.name,
                    "name": "get_source_excerpt",
                    "arguments": {
                        "path": path,
                        "start_line": 1,
                        "end_line": min(source.line_count or 120, 120),
                    },
                }
            )
            scheduled.add(key)
        key = "search:" + unit.name
        if key not in actions and candidates:
            symbol = next(
                (
                    symbol
                    for symbol in tools.accessible_snapshot.symbols
                    if symbol.file_id in unit.file_ids
                    and symbol.kind in {"class", "function", "interface"}
                ),
                None,
            )
            query = (
                symbol.name
                if symbol
                else PurePosixPath(files[unit.file_ids[0]].path).stem
            )
            tasks.append(
                {
                    "key": key,
                    "unit": unit.name,
                    "name": "search_repository_text",
                    "arguments": {"query": query, "limit": 10},
                }
            )
    return tasks


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
    gaps = [
        item
        for item in relationship_coverage(tools, report)
        if item["status"] == "uninvestigated"
        or (
            item["status"] == "unresolved"
            and not any(
                entry.unit_name == item["unit_name"] and entry.status == "unresolved"
                for entry in report.relationship_investigations
            )
        )
    ]
    if gaps:
        raise EvidenceGap(
            "Investigate module connections before closing, or declare explicit scoped unresolved investigations: "
            + str(
                [
                    item
                    | {
                        "pending_path_count": len(item["pending_paths"]),
                        "pending_paths": item["pending_paths"][:8],
                    }
                    for item in gaps
                ]
            )
        )


def relationship_coverage(tools, report, *, source_records=None):
    """Compare report connections with deterministic internal relationship hints."""
    if report is None:
        return []
    from server.project_analysis.project_architecture.diagram import report_connections

    snapshot = tools.accessible_snapshot
    files = {source.id: source for source in snapshot.files}
    owners = {symbol.id: symbol.file_id for symbol in snapshot.symbols}
    implementation = {
        source.id for sources in application_files(tools).values() for source in sources
    }
    membership = {}
    for unit in report.organization:
        for file_id in unit.file_ids:
            membership.setdefault(file_id, set()).add(unit.name)
    sources = {
        record.id: record.file_id
        for record in (
            tools.retrieved_evidence if source_records is None else source_records
        )
        if record.kind == "source"
    }
    links = [
        edge
        for _, edge in report_connections(report)
        if edge.description.status == "supported"
    ]
    pairs = {(edge.source_unit, edge.target_unit) for edge in links}
    units = {unit.name: unit for unit in report.organization}

    def covers_boundary(edge, source, target):
        cited = {
            sources[identifier]
            for identifier in edge.description.evidence_ids
            if identifier in sources
        }
        if not cited.intersection({source, target}):
            return False
        # Reuse endpoint responsibility evidence only for the resolved structural
        # boundary being checked, matching report reference-validation behavior.
        for name in (edge.source_unit, edge.target_unit):
            endpoint = units.get(name)
            if endpoint and endpoint.responsibility.status == "supported":
                cited.update(
                    sources[identifier]
                    for identifier in endpoint.responsibility.evidence_ids
                    if identifier in sources
                )
        return {source, target} <= cited

    entries = {entry.unit_name: entry for entry in report.relationship_investigations}
    result = []
    for unit in report.organization:
        pending_paths, pending_units, neighbors = set(), set(), set()
        for relation in snapshot.relationships:
            if relation.resolution != "internal":
                continue
            source = owners.get(relation.source_id, relation.source_id)
            target = owners.get(relation.target_id, relation.target_id)
            if source not in implementation or target not in implementation:
                continue
            source_names, target_names = (
                membership.get(source, set()),
                membership.get(target, set()),
            )
            if (
                unit.name not in source_names | target_names
                or unit.name in source_names & target_names
            ):
                continue
            other_file = target if unit.name in source_names else source
            other_names = target_names if unit.name in source_names else source_names
            neighbors.add(files[other_file].path)
            accounted = any(
                edge.source_unit in source_names
                and edge.target_unit in target_names
                and covers_boundary(edge, source, target)
                for edge in links
            )
            if not accounted:
                pending_paths.add(files[other_file].path)
                own_file = source if unit.name in source_names else target
                if own_file not in sources.values():
                    pending_paths.add(files[own_file].path)
                pending_units.update(other_names - {unit.name})
        entry = entries.get(unit.name)
        linked = any(unit.name in pair for pair in pairs)
        if entry is None:
            status, reason = (
                "uninvestigated",
                "No explicit investigation of incoming/outgoing connections or scoped isolation was reported.",
            )
        elif entry.status == "unresolved":
            status, reason = "unresolved", entry.assessment.statement
        elif entry.status == "isolated" and not neighbors and not linked:
            status, reason = (
                "isolated",
                "Scoped isolation was reported with source evidence; semantic review must assess the absence claim.",
            )
        elif entry.status == "connected" and linked and not pending_paths:
            status, reason = (
                "connected",
                "Supported report connections account for known cross-unit structural hints; this is not proof of complete runtime connectivity.",
            )
        else:
            status, reason = (
                "unresolved",
                "Reported connection coverage conflicts with structural hints or lacks supported connections; inspect the pending endpoints or declare unresolved scope.",
            )
        result.append(
            {
                "unit_name": unit.name,
                "status": status,
                "pending_paths": sorted(pending_paths),
                "pending_units": sorted(pending_units),
                "reason": reason,
                "resolution_blocker": entry.resolution_blocker
                if entry and status == "unresolved"
                else None,
                "blocker_reason": entry.blocker_reason
                if entry and status == "unresolved"
                else None,
            }
        )
    return result
