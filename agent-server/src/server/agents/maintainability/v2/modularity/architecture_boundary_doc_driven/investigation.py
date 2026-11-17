"""Small code-backed navigation and citation projections for the current task."""

from .schemas import BoundaryToolQuery


def complete_citation_links(conclusion, catalog):
    """Complete mechanical links to already delivered, explicitly named source.

    No source is retrieved or selected from prose. Only exact component/scope
    paths and examined relationship IDs chosen by the investigator can anchor
    candidate citation completion. An assessment must still choose its own source
    IDs; only an omitted scope can be derived from those exact citations.
    """
    if len(conclusion.limitations) >= 40:
        return conclusion
    sources = catalog["source_evidence_by_component"]
    source_paths = {key: path for path, ids in sources.items() for key in ids}
    edges = {edge["id"]: edge for edge in catalog["examined_relationships"]}
    changes = []

    def citations(ids, paths, relationships=()):
        paths = list(paths)
        for identifier in relationships:
            if identifier in edges:
                paths.extend([edges[identifier]["source_path"], edges[identifier]["target_path"]])
        return list(dict.fromkeys([*ids, *(key for path in paths for key in sources.get(path, []))]))

    candidates = []
    for candidate in conclusion.candidates:
        ids = citations(candidate.evidence_ids, candidate.components, candidate.relationship_ids)
        if ids != candidate.evidence_ids:
            changes.append(f"{candidate.id}.evidence_ids: {candidate.evidence_ids} -> {ids}")
        candidates.append(candidate.model_copy(update={"evidence_ids": ids}))
    assessments = []
    for assessment in conclusion.claim_assessments:
        scope = assessment.scope_paths or list(dict.fromkeys(source_paths[key]
            for key in assessment.code_evidence_ids if key in source_paths))
        if scope != assessment.scope_paths:
            changes.append(f"claim:{assessment.claim_id}: scope={assessment.scope_paths} -> {scope}")
        assessments.append(assessment.model_copy(update={"scope_paths": scope}))
    ids = citations(conclusion.evidence_ids, conclusion.components)
    delivered = {ref["id"] for ref in catalog["evidence"]}
    ids = list(dict.fromkeys([*ids, *(key for candidate in candidates for key in candidate.evidence_ids if key in delivered),
                             *(key for item in assessments for key in item.code_evidence_ids if key in delivered)]))
    if ids != conclusion.evidence_ids:
        changes.append(f"conclusion.evidence_ids: {conclusion.evidence_ids} -> {ids}")
    if not changes:
        return conclusion
    # Canonical limits and types remain strict after host-side completion.
    payload = conclusion.model_dump() | {"evidence_ids": ids,
        "candidates": [candidate.model_dump() for candidate in candidates],
        "claim_assessments": [item.model_dump() for item in assessments],
        "limitations": [*conclusion.limitations, "Host completed delivered-source citation links only; verdicts and narratives unchanged. " + "; ".join(changes)]}
    try:
        return type(conclusion).model_validate(payload)
    except ValueError:
        return conclusion  # Do not truncate collections or bypass canonical bounds.


def normalize_candidate_links(conclusion):
    """Remove favorable references only from an independently contradicted claim.

    Unknown IDs and unsupported candidates remain invalid. Never manufacture a
    contradiction, change a verdict, or turn a documentary candidate code-first.
    """
    statuses = {item.claim_id: item.status for item in conclusion.claim_assessments}
    candidates, notes = [], []
    for candidate in conclusion.candidates:
        ids = candidate.document_claim_ids
        favorable = [key for key in ids if statuses.get(key) in {"supported", "not_applicable"}]
        if (favorable and any(statuses.get(key) == "contradicted" for key in ids)
                and len(conclusion.limitations) + len(notes) < 40):
            candidate = candidate.model_copy(update={"document_claim_ids": [key for key in ids if key not in favorable]})
            notes.append(f"Host removed favorable documentary references from {candidate.id}: {', '.join(favorable)}. Original assessment verdicts and narrative are unchanged.")
        candidates.append(candidate)
    return conclusion.model_copy(update={"candidates": candidates,
        "limitations": list(dict.fromkeys([*conclusion.limitations, *notes]))})


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
    # Initially verified endpoints precede incidental scope files.
    endpoint_paths = [path for ref in task.structural_signal.relationships[:1]
                      for path in (ref.source_path, ref.target_path)]
    for path in list(dict.fromkeys([*endpoint_paths, *task.scope]))[:4]:
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
        elif code == "dependency_endpoints_source_not_inspected":
            cited_paths = {ref["path"] for ref in cited if ref["kind"] == "source"}
            for edge in catalog["examined_relationships"]:
                if edge["id"] not in subject.relationship_ids:
                    continue
                for path in (edge["source_path"], edge["target_path"]):
                    if path and path not in cited_paths:
                        errors.append({"subject_id": subject_id, "field": "evidence_ids",
                            "relationship_id": edge["id"], "missing_endpoint_path": path,
                            "available_source_evidence_ids": catalog["source_evidence_by_component"].get(path, []),
                            "source_required": path not in catalog["source_evidence_by_component"]})
        elif code == "candidate_document_claim_mismatch" and subject_id != "conclusion":
            assessments = {item.claim_id: item for item in conclusion.claim_assessments}
            errors.append({"subject_id": subject_id, "field": "document_claim_ids",
                "claim_statuses": {key: assessments[key].status if key in assessments else "missing"
                                   for key in subject.document_claim_ids},
                "contradicted_claim_evidence": {key: item.code_evidence_ids for key, item in assessments.items()
                                               if item.status == "contradicted"},
                "rule": "Link only independently contradicted claims and cite their source. Permissions, supported and not_applicable assessments are not contradictions. Never change assessment status to repair a candidate."})
        else:
            errors.append({"subject_id": subject_id, "code": code,
                "current_references": {field: getattr(subject, field) for field in
                    ("components", "evidence_ids", "symbol_ids", "relationship_ids")}})
    for assessment in conclusion.claim_assessments:
        subject_id = "claim:" + assessment.claim_id
        if code == "unknown_or_undelivered_evidence":
            errors.extend({"subject_id": subject_id, "field": "code_evidence_ids", "invalid_value": key[:200]}
                for key in set(assessment.code_evidence_ids) - refs.keys())
        elif code in {"uninspected_component", "claim_assessment_requires_source", "dependency_endpoints_source_not_inspected"}:
            cited_paths = {refs[key]["path"] for key in assessment.code_evidence_ids
                           if key in refs and refs[key]["kind"] == "source"}
            missing_paths = set(assessment.scope_paths) - cited_paths
            if code == "dependency_endpoints_source_not_inspected":
                for edge in catalog["examined_relationships"]:
                    if edge["id"] in conclusion.relationship_ids and edge["source_path"] in cited_paths:
                        missing_paths.update(path for path in (edge["source_path"], edge["target_path"])
                                             if path and path not in cited_paths)
            if missing_paths or (assessment.status in {"supported", "contradicted"} and not cited_paths):
                errors.append({"subject_id": subject_id, "field": "code_evidence_ids",
                    "scope_paths": assessment.scope_paths, "current_values": assessment.code_evidence_ids,
                    "missing_source_paths": sorted(missing_paths),
                    "available_source_evidence_by_component": catalog["source_evidence_by_component"],
                    "allowed_fields": ["code_evidence_ids", "scope_paths"],
                    "instruction": "Cite source for this assessment itself, including both endpoints of its referenced dependency. Request tools if missing. Do not patch scope_paths on conclusion or candidates."})
        elif code == "claim_evidence_not_in_conclusion":
            errors.append({"subject_id": "conclusion", "field": "evidence_ids",
                "missing_assessment_evidence_ids": sorted(set(assessment.code_evidence_ids) - set(conclusion.evidence_ids))})
    return errors
