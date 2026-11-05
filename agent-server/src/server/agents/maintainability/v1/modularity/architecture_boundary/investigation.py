"""Small code-backed navigation and citation projections for the current task."""

from .schemas import BoundaryToolQuery


def relationship_query(snapshot, reference):
    matches = [item for item in snapshot.relationships if
        (item.source_id, item.target_id, item.kind) == (reference.source_id, reference.target_id, reference.kind)]
    return {"tool": "list_relationships", "arguments": {
        "source_id": reference.source_id, "target_id": reference.target_id, "kind": reference.kind,
        "offset": next((index for index, item in enumerate(matches) if item.id == reference.id), 0), "limit": 1}}


def initial_queries(snapshot, task, enabled):
    queries = []
    symbols = {item.id: item for item in snapshot.symbols}
    evidence = {item.id: item for item in snapshot.evidence}
    indexed = {item.id: item for item in snapshot.relationships}
    anchors = {}
    # Inspect the primary indexed edge, rather than treating its planning ID as
    # an already examined relationship. Other planned edges remain navigation.
    for ref in task.structural_signal.relationships[:1]:
        queries.append(BoundaryToolQuery(**relationship_query(snapshot, ref),
            reason="Verify the primary planned relationship in the repository index."))
        relationship = indexed.get(ref.id)
        if relationship:
            for identifier in relationship.evidence_ids:
                record = evidence.get(identifier)
                if record and record.start_line:
                    anchors.setdefault(record.file_id, record.start_line)
        for identifier in (ref.source_id, ref.target_id):
            symbol = symbols.get(identifier)
            if symbol:
                anchors.setdefault(symbol.file_id, symbol.start_line)
    for identifier in task.structural_signal.symbol_ids:
        if identifier in symbols:
            symbol = symbols[identifier]
            anchors.setdefault(symbol.file_id, symbol.start_line)
    for link in task.structural_signal.integration_links:
        for point in [link.client, *link.endpoints, *link.binding_points]:
            anchors.setdefault(point.file_id, point.start_line)
    files = {file.path: file for file in snapshot.files}
    for path in task.scope[:4]:
        file = files.get(path)
        if file and file.line_count:
            start = max(1, anchors.get(file.id, 1) - 3)
            queries.append(BoundaryToolQuery(tool="get_source_excerpt", arguments={
                "path": path, "start_line": start, "end_line": min(file.line_count, start + 39)},
                reason="Inspect a bounded declaration/use range at the planned boundary endpoint."))
    return [query for query in queries if query.tool in enabled]


def examined_relationships(snapshot, state):
    indexed = {item.id: item for item in snapshot.relationships}
    result = {}
    for key in state["active_query_keys"]:
        view = state["query_cache"][key]
        if view["tool_name"] != "list_relationships" or view["status"] != "ok":
            continue
        for row in view.get("data", {}).get("items", []):
            relationship = indexed.get(row.get("id"))
            if relationship and (row.get("source_id"), row.get("target_id")) == (relationship.source_id, relationship.target_id):
                result[relationship.id] = relationship
    return result


def reference_catalog(snapshot, references, relationships, task):
    sources = {}
    for ref in references:
        if ref.kind == "source":
            sources.setdefault(ref.path, []).append(ref.id)
    owners = {item.id: item.file_id for item in snapshot.symbols}
    paths = {item.id: item.path for item in snapshot.files}
    edges = []
    for identifier, relationship in relationships.items():
        endpoints = [paths.get(owners.get(entity, entity)) for entity in (relationship.source_id, relationship.target_id)]
        edges.append({"id": identifier, "kind": relationship.kind, "source_path": endpoints[0], "target_path": endpoints[1],
            "source_evidence_ids": {path: sources.get(path, []) for path in endpoints if path},
            "missing_source_paths": [path for path in endpoints if path not in sources]})
    return {"source_evidence_by_component": sources, "examined_relationships": edges,
        "planned_only_relationship_ids": [ref.id for ref in task.structural_signal.relationships if ref.id not in relationships],
        "verification_queries": {ref.id: relationship_query(snapshot, ref)
            for ref in task.structural_signal.relationships if ref.id not in relationships},
        "evidence": [{key: getattr(ref, key) for key in ("id", "path", "kind", "file_id", "start_line", "end_line", "symbol_ids")}
            for ref in references]}


def reference_errors(turn, code, catalog):
    """Specific correction data only, never an exception's raw input/message."""
    conclusion = turn.conclusion
    if conclusion is None:
        return []
    refs = {ref["id"]: ref for ref in catalog["evidence"]}
    relationships = {edge["id"] for edge in catalog["examined_relationships"]}
    errors = []
    for subject_id, subject in [("conclusion", conclusion), *((candidate.id, candidate) for candidate in conclusion.candidates)]:
        cited = [refs[key] for key in subject.evidence_ids if key in refs]
        if code == "uninspected_component":
            inspected = {ref["path"] for ref in cited if ref["kind"] == "source" or conclusion.status == "inconclusive"}
            for path in set(subject.components) - inspected:
                errors.append({"subject_id": subject_id, "field": "components", "invalid_value": path[:200],
                    "available_source_evidence_ids": catalog["source_evidence_by_component"].get(path, []),
                    "source_required": path not in catalog["source_evidence_by_component"]})
        elif code == "unexamined_relationship":
            errors.extend({"subject_id": subject_id, "field": "relationship_ids", "invalid_value": identifier[:200],
                "planned_only": identifier in catalog["planned_only_relationship_ids"]}
                for identifier in set(subject.relationship_ids) - relationships)
        elif code == "unknown_or_undelivered_evidence":
            errors.extend({"subject_id": subject_id, "field": "evidence_ids", "invalid_value": identifier[:200]}
                for identifier in set(subject.evidence_ids) - refs.keys())
        elif code == "uninspected_symbol":
            available = {symbol for ref in cited if ref["kind"] == "source" for symbol in ref["symbol_ids"]}
            errors.extend({"subject_id": subject_id, "field": "symbol_ids", "invalid_value": identifier[:200],
                "available_symbol_ids": sorted(available)} for identifier in set(subject.symbol_ids) - available)
        else:
            errors.append({"subject_id": subject_id, "code": code,
                "current_references": {field: getattr(subject, field) for field in
                    ("components", "evidence_ids", "symbol_ids", "relationship_ids")}})
    return errors
