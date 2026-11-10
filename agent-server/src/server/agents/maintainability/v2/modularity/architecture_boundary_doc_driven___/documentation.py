"""Conservative documentary planning seeds. No code verdicts or source analysis."""

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

from server.services.document_indexing.service import identifier
from server.services.repository_analysis.context import create_identifier

from .document_mapping import DocumentCodeResolver, relation_applies
from .schemas import (
    BoundaryInvestigation,
    DocumentClaimPortion,
    DocumentClaimRecord,
    StructuralQuery,
    StructuralRelationship,
    StructuralSignal,
)


def claim_identity(claim, context):
    data = claim.model_dump(mode="json")
    for key in ("section_ids", "related_subjects"):
        data[key] = sorted(set(data[key]))
    data["evidence"] = sorted(data["evidence"], key=lambda item: json.dumps(item, sort_keys=True))
    provenance = {
        "index": context.document_index.model_dump() if context.document_index else None,
        "sections": {key: context.section_paths.get(key) for key in sorted(claim.section_ids)},
        "documents": sorted(
            (document.model_dump() for document in context.consulted_documents
             if document.path in {context.section_paths.get(key) for key in claim.section_ids}),
            key=lambda item: item["path"],
        ),
    }
    return "document_claim_" + hashlib.sha256(
        json.dumps([data, provenance], sort_keys=True, ensure_ascii=True).encode()
    ).hexdigest()


def _domain(claim):
    """Conservative bilingual gate, not a semantic classification of requirements.

    Interprets category, constraint, statement, subject, related subjects,
    reasoning and documentary evidence together. A purely functional,
    security or data obligation without an architectural mechanism stays out;
    a permission or future plan never becomes a current prohibition.
    """
    text = " ".join([claim.subject, claim.statement, *claim.related_subjects, claim.reasoning]).casefold()
    if claim.certainty != "explicit":
        return None, "uncertain assertion; explicit scope/obligation needs clarification"
    if re.search(r"\b(proposed|proposal|considered alternative|hypothetical|for example|e\.g\.|"
                 r"propuesto|propuesta|alternativa considerada|hipotético|hipotética|por ejemplo|"
                 r"a futuro|en el futuro|planned|future work)\b", text):
        return None, "proposal, example or future plan is not an adopted boundary obligation"
    if claim.constraint == "allowed" and re.search(
            r"\b(legacy|deuda técnica|deuda tecnica|grandfathered|temporalmente|until migration|"
            r"antes de la migración|migración pendiente|a migrar)\b", text):
        return None, "legacy/migration allowance is not a current boundary obligation"
    if re.search(r"\b(eslint|no-restricted-imports)\b", text):
        # A mixed claim can carry a verifiable dependency obligation next to a
        # lint configuration; only a purely configurational one is discarded.
        clauses = [segment.strip() for segment in re.split(
            r"[,;.]|\s+\by\b\s+|\s+\band\b\s+", text) if segment.strip()]
        non_config = " ".join(
            clause for clause in clauses
            if not re.search(r"\b(eslint|no-restricted-imports)\b", clause))
        strong_architecture = re.search(
            r"\b(no debe|no deben|no puede|no pueden|se prohíbe|prohibido|únicamente|solamente|"
            r"must not|shall not|should not|debe pasar por|deben pasar por|depende de|dependan de|"
            r"no importar|no importan|no importa)\b", non_config)
        if not strong_architecture:
            return None, "tool-configuration obligation; it regulates its own configuration, not a code boundary verdict"
    normative = claim.constraint != "unspecified" or re.search(
        r"\b(must|shall|should|may|only|allowed imports?|permitted|prohibit\w*|se prohíbe|prohibido|"
        r"prohíbe|únicamente|solamente|debe pasar por|deben pasar por|pasar por|a través de|"
        r"no debe|no deben|no puede|no pueden|tiene que|tienen que|point inward|remain acyclic|"
        r"stays? in)\b", text)
    if not normative:
        return None, "description without a normative boundary obligation"
    if claim.category not in {"constraints", "relationships", "interfaces_and_contracts", "architectural_decisions", "architectural_style", "components"}:
        return None, "outside boundary planning categories"
    has_mechanism = re.search(
        r"\b(import(?:s|ing|ed|er|ers)?|importa\w*|importar|dependenc\w*|dependencia\w*|depend on|depends on|depende de|"
        r"dependa de|dependan de|"
        r"encapsulat\w*|encapsul\w*|private state|private storage|estado privado|public api|"
        r"public contract|public port|interfaz pública|cyclic|acyclic|cycles?|ciclo|cíclic[oa]|"
        r"composition|composición|construct\w*|inyect\w*|assembl\w*|ensambl\w*|adapters?|"
        r"adaptador\w*|integration|integración|transport|transporte|interfaces?|"
        r"boundar\w*|frontera|allowed imports?|pasar por|a través de|únicamente|"
        r"(?:utilizar|usar)[^.]{0,60}?(?:capa|layer|framework)|framework|"
        r"only (?:through|via|may|can))\b|→|->", text)
    if not has_mechanism:
        return None, "no boundary mechanism; functional/security/data obligations are not boundary tasks"
    if re.search(r"\b(private state|private storage|estado privado|almacenamiento privado|encapsulat\w*|"
                 r"encapsul\w*|public api|public contract|public port|interfaz pública|contrato público|"
                 r"acceso directo(?: a)?|no debe acceder directamente|debe encapsular|ocultar (?:la )?implementaci)\b", text):
        return "encapsulation", "explicit access/ownership boundary"
    if re.search(r"\b(cyclic|acyclic|cycles?|ciclo|cíclic[oa]|acíclic[oa]|dependencias circulares)\b", text):
        return "acyclicity", "explicit cyclic-dependency boundary"
    if re.search(r"\b\w+\s*(?:→|->)\s*\w+", text):
        if re.search(r"\b(composition|composición|construct\w*|inject\w*|assembl\w*|ensambl\w*)\b", text):
            return "composition", "explicit construction/composition boundary"
        return "dependency", "explicit dependency/interface boundary"
    if re.search(r"\b(composition|composición|construct\w*|inject\w*|assembl\w*|ensambl\w*|construye)\b", text) and re.search(
            r"\b(adapters?|adaptador\w*|ports?|puertos?|layers?|capas?|composition|composición|bindings?|ensamblaje)\b", text):
        return "composition", "explicit construction/composition boundary"
    if re.search(
            r"\b(import(?:s|ing|ed|er|ers)?|importa\w*|importar|dependenc\w*|dependencia\w*|depend on|depends on|depende de|"
            r"dependa de|dependan de|"
            r"no debe importar|no importar|únicamente|solamente|debe pasar por|deben pasar por|"
            r"pasar por|a través de|vía|through|allowed imports?|permitted|permitid[oa]s?|"
            r"only (?:through|via|may|can)|ports?|composition|composición|layers?|capas?|cyclic|acyclic|cycle|"
            r"(?:utilizar|usar)[^.]{0,60}?(?:capa|layer|framework)|"
            r"(?:debe|deben|tiene que|tienen que) (?:pasar por|ir a|depender de|importar|usar|acceder a)|"
            r"no (?:debe|deben|puede|pueden) (?:importar|depender|acceder))\b", text):
        return "dependency", "explicit dependency/interface boundary"
    if re.search(r"\b(adapters?|adaptador\w*|integration|integración|transport|transporte)\b", text) and re.search(
            r"\b(interfaces?|boundar\w*|frontera|límite|implement\w*|access|acceso|isolat\w*|aislam\w*)\b", text):
        return "integration", "explicit adapter/integration boundary"
    return None, "no boundary mechanism; functional/security/data obligations are not boundary tasks"


def prepare_documentation(snapshot, request, files, seeds, file_projects, *, check):
    context = getattr(request, "documented_architecture", None)
    records, tasks = {}, []
    if context is None:
        return tasks, records, {"context_status": "not_provided", "received": 0}, []
    index = context.document_index
    compatible = bool(index and snapshot.repository.commit and index.commit == snapshot.repository.commit
        and index.repository_id == identifier(str(Path(snapshot.repository.root_path).resolve())))
    warnings = []
    if not compatible:
        warnings.append("Documentary repository/commit is incompatible with this snapshot; no documentary opportunity is valid.")
    if context.execution_status != "complete" or context.validation_errors or context.knowledge_issues:
        warnings.append("Documentary context is partial, uncertain or technically limited; it is not an exhaustive specification.")
    symbols = {symbol.id: symbol for symbol in snapshot.symbols if symbol.file_id in files}
    resolver = DocumentCodeResolver(files, symbols.values(), check)
    # Only provenance-consistent explicit ownership descriptions can establish
    # a documented group label. No built-in Domain/Application folder vocabulary.
    documents = {document.path: document for document in context.consulted_documents}
    label_claims = [claim for claim in context.knowledge if compatible and context.execution_status != "failed"
        and all(context.section_paths.get(key) in documents for key in claim.section_ids)
        and all(all(getattr(documents[context.section_paths[key]], field) == getattr(index, field)
            for field in ("index_id", "repository_id", "commit")) for key in claim.section_ids)
        and all(evidence.quote and evidence.section_id in claim.section_ids for evidence in claim.evidence)
        and not any(set(issue.section_ids) & set(claim.section_ids) for issue in context.knowledge_issues)
        and not any(error.target != "execution" and (not error.section_ids or set(error.section_ids) & set(claim.section_ids))
            for error in context.validation_errors)]
    resolver.add_documented_labels(label_claims)
    owners = {**{key: key for key in files}, **{key: symbol.file_id for key, symbol in symbols.items()}}
    cross_project_pairs = set()
    edges = []
    for relation in snapshot.relationships:
        check()
        a, b = owners.get(relation.source_id), owners.get(relation.target_id)
        if relation.resolution == "internal" and a and b and a != b:
            edges.append((relation, a, b))
        if relation.resolution == "internal" and a and b and file_projects[a] != file_projects[b]:
            cross_project_pairs.add((a, b))
    buckets = defaultdict(list)
    for claim in context.knowledge:
        check()
        claim_id = claim_identity(claim, context)
        if claim_id in records:
            continue
        paths = {key: context.section_paths[key] for key in claim.section_ids if key in context.section_paths}
        family, reason = _domain(claim)
        status = "not_applicable" if family is None else "unmapped"
        if not compatible:
            status, reason = "incompatible", "repository or commit mismatch"
        elif not paths or len(paths) != len(set(claim.section_ids)) or any(
            path not in documents or any(getattr(documents[path], key) != getattr(index, key)
                for key in ("index_id", "repository_id", "commit")) for path in paths.values()
        ) or {evidence.section_id for evidence in claim.evidence} != set(claim.section_ids) or any(
            evidence.section_id not in paths or not evidence.quote
            or evidence.end_line > documents[paths[evidence.section_id]].line_count
            for evidence in claim.evidence):
            status, reason = "invalid_reference", "missing/inconsistent documentary provenance"
        elif any(issue.kind in {"ambiguity", "discrepancy", "unknown"} and set(issue.section_ids) & set(claim.section_ids)
                 for issue in context.knowledge_issues) or any(
                     error.target != "execution" and (not error.section_ids or set(error.section_ids) & set(claim.section_ids))
                     for error in context.validation_errors):
            status, reason = "uncertain", "related documentary uncertainty or validation failure requires clarification"
        elif claim.certainty != "explicit":
            status = "uncertain"
        elif context.execution_status == "failed":
            status, reason = "uncertain", "failed documentary extraction is not a trusted normative input"
        records[claim_id] = DocumentClaimRecord(claim=claim, document_index=index, section_paths=paths,
            status=status, reason=reason, boundary_family=family)
        if status != "unmapped":
            continue
        text = " ".join([claim.subject, claim.statement, *claim.related_subjects]).replace("\\", "/")
        mapping = resolver.resolve(text)
        subject = resolver.resolve(claim.subject)
        # Titles such as "Infrastructure presentation isolation" name both
        # sides. Prefer the grammatical owner before the normative verb, so a
        # prohibition is not accidentally applied in the reverse direction.
        source_clause = re.split(r"\b(?:must|shall|should|may|allowed imports?|permitted imports?|"
            r"debe|deben|puede|pueden|tiene que|tienen que|deberá|deberán)\b",
            claim.statement, maxsplit=1, flags=re.IGNORECASE)
        if len(source_clause) > 1:
            statement_subject = resolver.resolve(source_clause[0])
            if statement_subject["ids"]:
                subject = statement_subject
        # A dependency chain (Route → Service → Prisma) names its origin first.
        if "→" in claim.statement or "->" in claim.statement:
            chain_subject = resolver.resolve(re.split(r"\s*(?:→|->)\s*", claim.statement, maxsplit=1)[0])
            if chain_subject["ids"]:
                subject = chain_subject
        # Spanish sentence forms name the regulated layer explicitly:
        # "importar X en la Capa Route" or "Solo Service puede importar X".
        if not subject["ids"]:
            clause = re.search(r"\b(?:en|para|desde)\s+(?:la\s+)?(capa\s+\w+|layer\s+\w+|\w+\s+layer)\b",
                claim.statement, re.IGNORECASE)
            if clause:
                layer_subject = resolver.resolve(clause.group(1))
                if layer_subject["ids"]:
                    subject = layer_subject
        if not subject["ids"]:
            actor = re.search(r"\bsolo\s+([A-Za-z_][\w]*(?:\s+[A-Za-z_][\w]*)?)\s+puede(?:n)?\b",
                claim.statement, re.IGNORECASE)
            if actor:
                actor_subject = resolver.resolve(actor.group(1))
                if actor_subject["ids"]:
                    subject = actor_subject
        # Explicitly named exceptions are excluded from automatic applicability.
        exception = re.split(r"\b(?:except|unless|excluding|excepto|salvo|a menos que|excluyendo)\b",
            claim.statement, maxsplit=1, flags=re.IGNORECASE)
        excluded = resolver.resolve(exception[1])["ids"] if len(exception) > 1 else set()
        matched_set = set(mapping["ids"] - excluded)
        origin_note = ""
        matched_set -= excluded
        matched = sorted(matched_set)
        records[claim_id] = records[claim_id].model_copy(update={
            "mapping_basis": mapping["basis"], "unresolved_references": mapping["unresolved"],
            "symbol_ids": sorted(mapping["symbols"]),
            "owner_paths": {key: sorted(files[item].path for item in values - excluded)
                for key, values in mapping["matches"].items()},
            "subject_paths": sorted(files[key].path for key in subject["ids"] - excluded),
            "excluded_paths": sorted(files[key].path for key in excluded),
            "scope_paths": sorted(files[key].path for key in matched)})
        # Resolved references stay usable when another reference is ambiguous or
        # unresolved; uncertainty is recorded, never treated as verified.
        if not matched or not set(matched) & seeds or (family == "dependency" and not subject["ids"]):
            records[claim_id] = records[claim_id].model_copy(update={"reason":
                "regulated subject unresolved; an imported destination alone cannot locate the obligated party"
                if family == "dependency" and not subject["ids"] else
                "ambiguous indexed ownership; qualified root/declaration required" if mapping["ambiguous"] else
                "no exact or uniquely corroborated indexed owner in requested scope"})
            continue
        # Independently owned project scopes are separate probes. Group only
        # identical mapped scopes AND boundary mechanism, never lexical similarity.
        by_project = defaultdict(list)
        for key in matched:
            by_project[file_projects[key]].append(key)
        records[claim_id] = records[claim_id].model_copy(update={"status": "applicable", "reason": reason + origin_note,
            "scope_paths": sorted(files[key].path for key in matched)})
        cross_project_edge = any(a in matched and b in matched for a, b in cross_project_pairs)
        groups = [(tuple(sorted(by_project)), matched)] if cross_project_edge else [
            ((project,), ids) for project, ids in sorted(by_project.items())]
        eligible_edges = [(r, a, b) for r, a, b in edges
            if (a in seeds or b in seeds) and relation_applies(records[claim_id], files[a].path, files[b].path)]
        # Broad rules and cycle obligations are partitioned by actual directed
        # interactions first; remaining declared owners get bounded source probes.
        portions = []
        if len(matched) > 12 or family == "acyclicity":
            seen_pairs = set()
            # Observed runtime relations outrank type-only ones and lexical order.
            for r, a, b in sorted(eligible_edges, key=lambda edge: (
                    edge[0].kind == "type_only", files[edge[1]].path, files[edge[2]].path, edge[0].id)):
                check()
                pair = tuple(sorted((a, b)))
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    portions.append((tuple(sorted({file_projects[a], file_projects[b]})), list(pair)))
            represented = {key for _, ids in portions for key in ids}
            declared = {symbol.file_id for symbol in symbols.values()}
            for projects, ids in groups:
                remaining = sorted((key for key in ids if key not in represented and key in declared), key=lambda key: files[key].path)
                portions.extend((projects, remaining[start:start + 12]) for start in range(0, len(remaining), 12))
            represented = {key for _, ids in portions for key in ids}
            records[claim_id] = records[claim_id].model_copy(update={
                "unrepresented_paths": sorted(files[key].path for key in set(matched) - represented)})
        else:
            portions = groups
        for projects, ids in portions:
            # Exceptions accompany their scoped obligation; they never seed a
            # standalone investigation. The record stays applicable/traceable.
            if records[claim_id].claim.constraint == "exception":
                continue
            symbol_ids = tuple(sorted(key for key in mapping["symbols"] if symbols[key].file_id in ids))
            buckets[family, projects, tuple(sorted(ids)), symbol_ids].append(claim_id)
    for (family, projects, ids, symbol_ids), claim_ids in sorted(buckets.items()):
        check()
        bucket_records = [records[key] for key in claim_ids]
        # Regulated origins come first in scope (never alphabetical
        # first-file-as-origin): the investigator probes their outgoing
        # relations; destinations such as lib/prisma stay in scope only.
        subject_paths = sorted({path for item in bucket_records for path in item.subject_paths})
        all_paths = sorted(files[key].path for key in ids)
        paths = [path for path in all_paths if path in set(subject_paths)] + [
            path for path in all_paths if path not in set(subject_paths)]
        # Normative strength and mapping confidence drive host prioritization;
        # permissions/exceptions stay secondary and partial mappings demote.
        strong = any(item.claim.constraint in {"prohibited", "required"} for item in bucket_records)
        confirmed = any(item.mapping_basis in {"exact", "corroborated"} for item in bucket_records)
        priority = "high" if strong and confirmed else (
            "medium" if strong or any(item.claim.constraint == "unspecified" for item in bucket_records) else "low")
        basis = "corroborated" if any(item.mapping_basis == "corroborated" for item in bucket_records) else "indexed"
        has_observed = any(relation_applies(item, files[a].path, files[b].path)
            for item in bucket_records for _r, a, b in edges if a in ids and b in ids)
        probe_mode = ("Contrast the obligations with the observed indexed relations in this scope." if has_observed
            else "No planned relationship is assumed; discover the actual mechanism in code before judging.")
        # IDs denote a boundary objective, not a position or an observed violation.
        task_id = create_identifier("documented_boundary", snapshot.repository.snapshot_hash, family, *projects, *paths, *symbol_ids)
        file_keys = {files[key].path: key for key in ids}
        origin_paths = [path for path in paths if path in set(subject_paths)]
        # Exact correspondence between the regulated origin and its file ID;
        # without a verifiable origin there is no fallback: the task is
        # formulated as bounded discovery and the uncertainty is recorded.
        origin_id = file_keys.get(origin_paths[0]) if origin_paths else None
        origin_path = origin_paths[0] if origin_paths else paths[0]
        # Preserve observed directed relations as planned navigation only:
        # they are never examined evidence until tools verify them.
        refs, seen_relations = [], set()
        for item in bucket_records:
            for r, a, b in edges:
                if r.id in seen_relations or a not in ids or b not in ids:
                    continue
                if relation_applies(item, files[a].path, files[b].path):
                    seen_relations.add(r.id)
                    refs.append(StructuralRelationship(id=r.id, source_id=r.source_id, target_id=r.target_id,
                        source_path=files[a].path, target_path=files[b].path, kind=r.kind))
        refs.sort(key=lambda ref: (ref.source_path not in set(origin_paths), ref.source_path, ref.target_path, ref.id))
        refs = refs[:12]
        if refs:
            evidence_needed = ["Actual source declarations, dependency/access mechanisms and called implementations",
                "Compare every attached claim and its documentary scope, permissions and exceptions; documentation is not proof of implementation",
                "Record unsupported mappings and missing code evidence without a conformance verdict",
                "Verify each planned relationship from the indexed origin to its destination before citing it"]
        else:
            evidence_needed = ["Actual source declarations, dependency/access mechanisms and called implementations",
                "Compare every attached claim and its documentary scope, permissions and exceptions; documentation is not proof of implementation",
                "Record unsupported mappings and missing code evidence without a conformance verdict",
                "Discover the dependency/access mechanism from source and indexed relations; empty initial relations prove nothing"]
            if origin_id is None:
                evidence_needed.append("No verifiable regulated origin was located; discovery stays bounded to this scope.")
        probe_mode = ("Contrast the obligations with the observed indexed relations in this scope." if refs
            else "No planned relationship is assumed; discover the actual mechanism in code before judging.")
        if origin_id and refs:
            strategy = [StructuralQuery(tool="find_symbols", arguments={"file_path": origin_path, "limit": 10}),
                StructuralQuery(tool="list_relationships", arguments={
                    "source_id": refs[0].source_id, "target_id": refs[0].target_id, "kind": refs[0].kind, "limit": 10})]
        elif origin_id:
            strategy = [StructuralQuery(tool="find_symbols", arguments={"file_path": origin_path, "limit": 10}),
                StructuralQuery(tool="list_relationships", arguments={"source_id": origin_id, "limit": 10})]
        else:
            strategy = [StructuralQuery(tool="find_symbols", arguments={"file_path": origin_path, "limit": 10}),
                StructuralQuery(tool="list_relationships", arguments={"limit": 10})]
        task = BoundaryInvestigation(id=task_id, priority=priority, scope=paths, project_ids=list(projects),
            scope_kind="inter_application" if len(projects) > 1 else "internal",
            document_claim_ids=sorted(claim_ids),
            structural_signal=StructuralSignal(kind="documented_boundary", basis=basis,
                relationships=refs,
                symbol_ids=list(symbol_ids),
                observed=["Indexed ownership matches (document mapping: " +
                    ", ".join(sorted({records[key].mapping_basis for key in claim_ids})) + "): " + ", ".join(paths)],
                inference="The documentary obligation applies to these code owners only provisionally; inspect actual dependencies, public contracts and exceptions."),
            question=f"Do the actual {family} mechanisms in this indexed scope respect the attached documentary obligations, including permissions and exceptions? {probe_mode}",
            evidence_needed=evidence_needed,
            investigation_strategy=strategy,
            completion_condition="Each attached obligation has code-backed support or an explicit unresolved limitation; neither a defect nor compliance is presumed.")
        tasks.append(task)
        for claim_id in claim_ids:
            record = records[claim_id]
            portion = DocumentClaimPortion(id=create_identifier("document_portion", claim_id, family, *paths),
                scope_paths=paths, relationship_ids=sorted(r.id for r, a, b in edges
                    if a in ids and b in ids and relation_applies(record, files[a].path, files[b].path)),
                opportunity_ids=[task_id])
            records[claim_id] = record.model_copy(update={"opportunity_ids": [*record.opportunity_ids, task_id],
                "portions": [*record.portions, portion]})
    diagnostics = {"context_status": "compatible" if compatible else "incompatible",
        "execution_status": context.execution_status, "finalization_reason": context.finalization_reason,
        "coverage_assessment_status": context.coverage_assessment_status,
        "documentary_coverage_is_investigated_coverage": False,
        "knowledge_issues": [issue.model_dump(mode="json") for issue in context.knowledge_issues],
        "validation_errors": [error.model_dump(mode="json") for error in context.validation_errors],
        "received": len(context.knowledge), "unique": len(records)}
    return tasks, records, diagnostics, warnings


def _structural_match(task, record):
    kinds = {"cycle": {"acyclicity"}, "direction": {"dependency"},
        "encapsulation": {"encapsulation"}, "component_boundary": {"dependency", "encapsulation"},
        "integration": {"integration", "encapsulation", "dependency"}}
    if record.status != "applicable" or record.boundary_family not in kinds.get(task.structural_signal.kind, set()):
        return False
    if record.claim.constraint == "exception":
        return False  # Exceptions accompany their scoped obligation, never establish one.
    refs = task.structural_signal.relationships
    technical_symbols = set(task.structural_signal.symbol_ids) | {key for ref in refs for key in (ref.source_id, ref.target_id)}
    if record.symbol_ids and not set(record.symbol_ids) <= technical_symbols:
        return False
    if record.boundary_family == "acyclicity":
        if record.claim.constraint == "allowed" or not refs or not set(task.scope) <= set(record.scope_paths):
            return False
        return not set(task.scope) & set(record.excluded_paths) and any(
            relation_applies(record, ref.source_path, ref.target_path) for ref in refs)
    symbol_paths = {path for alias, paths in record.owner_paths.items()
        if alias in {record.claim.subject, *record.claim.related_subjects} for path in paths}
    if task.structural_signal.symbol_ids and symbol_paths and not symbol_paths & set(task.scope):
        return False
    if refs:
        return relation_applies(record, refs[0].source_path, refs[0].target_path)
    for link in task.structural_signal.integration_links:
        if any(relation_applies(record, link.client.path, point.path) for point in link.endpoints):
            return True
    return False


def link_structural_opportunities(candidates, records, check):
    """Reuse surviving structural objectives; replace only equivalent doc portions."""
    structural = [task for task in candidates if task.structural_signal.kind != "documented_boundary"]
    documentary = [task for task in candidates if task.structural_signal.kind == "documented_boundary"]
    linked = []
    for task in structural:
        check()
        claim_ids = [key for key, record in records.items() if _structural_match(task, record)]
        if claim_ids:
            # A separately extracted exception/permission is relevant only with
            # a real obligation and its explicitly localized code owner.
            obligations = list(claim_ids)
            claim_ids.extend(key for key, record in records.items() if record.status == "applicable"
                and record.claim.constraint == "exception" and set(record.scope_paths)
                and set(record.scope_paths) <= set(task.scope)
                and any(set(record.claim.section_ids) & set(records[other].claim.section_ids) for other in obligations))
        update = {"document_claim_ids": sorted(set(claim_ids))}
        if claim_ids:
            documentary_requirement = "Contrast all attached document_claim_ids against actual directed code mechanisms, including documented scope, permissions and exceptions; this probe cannot establish whole-claim compliance."
            update["evidence_needed"] = list(dict.fromkeys([*task.evidence_needed, documentary_requirement]))
        linked.append(task.model_copy(update=update))
    for key, record in list(records.items()):
        portions = []
        for portion in record.portions:
            equivalents = [task.id for task in linked if key in task.document_claim_ids
                and set(portion.scope_paths) <= set(task.scope)
                and (not portion.relationship_ids or set(portion.relationship_ids) <= {
                    ref.id for ref in task.structural_signal.relationships})]
            portions.append(portion.model_copy(update={"opportunity_ids": equivalents or portion.opportunity_ids}))
        linked_ids = [task.id for task in linked if key in task.document_claim_ids]
        records[key] = record.model_copy(update={"portions": portions,
            "opportunity_ids": sorted(set(linked_ids + [item for portion in portions for item in portion.opportunity_ids]))})
    for task in documentary:
        remaining = [key for key in task.document_claim_ids if any(task.id in portion.opportunity_ids for portion in records[key].portions)]
        if remaining:
            linked.append(task.model_copy(update={"document_claim_ids": remaining}))
    # Remove stale doc IDs from records whose grouped task was completely replaced.
    available = {task.id for task in linked}
    for key, record in list(records.items()):
        records[key] = record.model_copy(update={"opportunity_ids": sorted(set(record.opportunity_ids) & available)})
    return linked, records


def documentary_diagnostics(inventory, menu, selected):
    records = inventory.get("_document_claims", {})
    menu_ids = {key for task in menu for key in task.document_claim_ids}
    selected_ids = {key for task in selected for key in task.document_claim_ids}
    grouped = {key for key, record in records.items() if record.opportunity_ids}
    output = dict(inventory.get("documentary_diagnostics", {"received": 0, "context_status": "not_provided"}))
    statuses = defaultdict(list)
    for key, record in records.items():
        statuses[record.status].append(key)
    applicable_ids = {key for key, record in records.items() if record.status in {"applicable", "unmapped", "scope_limit"}}
    selected_for_claim = {key: {task.id for task in selected if key in task.document_claim_ids} for key in records}
    partial = {key for key in selected_ids if records[key].unresolved_references or records[key].unrepresented_paths
        or any(not set(portion.opportunity_ids) & selected_for_claim[key] for portion in records[key].portions)}
    complete_selection = selected_ids - partial
    all_tasks = inventory.get("_documentary_candidates", menu)
    structural_ids = {key for task in all_tasks if task.structural_signal.kind != "documented_boundary" for key in task.document_claim_ids}
    documentary_ids = {key for task in all_tasks if task.structural_signal.kind == "documented_boundary" for key in task.document_claim_ids}
    output.update(applicable=len(applicable_ids), mapped=len(statuses["applicable"]),
        grouped=len(grouped), selected=len(selected_ids), investigated=0,
        omitted_by_menu_or_context=len(grouped - menu_ids), not_selected=len(menu_ids - selected_ids),
        unmapped=len(statuses["unmapped"]), uncertain=len(statuses["uncertain"]),
        not_applicable=len(statuses["not_applicable"]), scope_limit=len(statuses["scope_limit"]),
        pending_claim_ids=sorted(applicable_ids - complete_selection),
        partially_selected_claim_ids=sorted(partial),
        omitted_claim_ids=sorted(grouped - menu_ids))
    initial_ids = inventory.get("_initial_document_claim_ids", menu_ids)
    output.update(linked_to_structural=len(structural_ids), represented_documentary=len(documentary_ids),
        structural_investigations_enriched=sum(bool(task.document_claim_ids) and task.structural_signal.kind != "documented_boundary" for task in all_tasks),
        documentary_opportunities_generated=sum(task.structural_signal.kind == "documented_boundary" for task in all_tasks),
        documentary_opportunities_selected=sum(task.structural_signal.kind == "documented_boundary" for task in selected),
        omitted_by_menu=len(grouped - set(initial_ids)), omitted_by_context=len(set(initial_ids) - menu_ids),
        partial=len(partial), fully_represented_by_selection=len(complete_selection),
        pending_information_claim_ids=sorted(key for key in applicable_ids if records[key].status == "unmapped"
            or records[key].unresolved_references or records[key].unrepresented_paths),
        not_applicable_claim_ids=sorted(statuses["not_applicable"]),
        pending_definition="Applicable obligations not fully represented by selected known-scope portions; never investigated coverage",
        pending_portions={key: [portion.id for portion in record.portions if not set(portion.opportunity_ids) & selected_for_claim[key]]
            for key, record in records.items() if key in applicable_ids},
        selected_claim_ids=sorted(selected_ids), linked_structural_claim_ids=sorted(structural_ids),
        documentary_claim_ids=sorted(documentary_ids),
        uncertain_claim_ids=sorted(statuses["uncertain"]),
        not_selected_claim_ids=sorted(menu_ids - selected_ids),
        mapping_counts={basis: sum(records[key].mapping_basis == basis for key in applicable_ids)
            for basis in ("exact", "corroborated", "ambiguous", "unmapped")})
    output["partially_omitted_claim_ids"] = sorted(key for key, record in records.items()
        if key in menu_ids and set(record.opportunity_ids) - {task.id for task in menu})
    output["by_status"] = {status: sorted(ids) for status, ids in statuses.items()}
    return output
