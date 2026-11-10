"""Bounded structural projections of the existing index, not a source analyzer."""

import re
from collections import Counter, defaultdict
from pathlib import PurePosixPath

from server.services.repository_analysis.architecture import find_import_cycles
from server.services.repository_analysis.context import (
    AnalysisContext,
    create_identifier,
)
from server.services.repository_analysis.testing import is_test_file

from .config import BoundaryConfig
from .documentation import (
    documentary_diagnostics,
    link_structural_opportunities,
    prepare_documentation,
)
from .integrations import discover_integrations
from .schemas import (
    BoundaryInvestigation,
    StructuralQuery,
    StructuralRelationship,
    StructuralSignal,
)


def nonproduction_path(path):
    path = path.casefold().replace("\\", "/")
    parts = PurePosixPath(path).parts
    return (is_test_file(path) or PurePosixPath(path).name == "conftest.py"
        or any(re.search(r"(?:^|[._-])(?:tests?|specs?|fixtures?|mocks?)(?:[._-]|$)", part)
            for part in parts))


def candidate_rank(task):
    return ({"high": 0, "medium": 1, "low": 2}[task.priority],
        {"corroborated": 0, "indexed": 1, "inferred": 2}[task.structural_signal.basis],
        len(task.scope), -len(task.structural_signal.relationships), task.id)


def balance_candidates(candidates, task_projects, limit, *, preferred=None):
    """Diversify the menu, or reorder only an explicitly supplied model selection."""
    if limit <= 0:
        return []
    preferences = {task.id: index for index, task in enumerate(preferred or ())}
    if preferred is not None:
        # An explicit empty selection is abstention, not permission to fill slots.
        candidates = [task for task in candidates if task.id in preferences]
    # The model can order equally grounded opportunities, not promote a weak
    # inferred API above indexed/corroborated boundary evidence.
    ranked = sorted(candidates, key=lambda task: (
        *candidate_rank(task)[:2], preferences.get(task.id, len(preferences)), *candidate_rank(task)[2:]))
    by_project = defaultdict(list)
    for task in ranked:
        for project in task_projects[task.id]:
            by_project[project].append(task)
    projects = sorted(by_project, key=lambda project: (candidate_rank(by_project[project][0]), project))
    selected, covered = [], set()
    for project in projects:
        if project not in covered:
            task = by_project[project][0]
            selected.append(task)
            covered.update(task_projects[task.id])
            if len(selected) >= limit:
                return selected
    coverage_counts = Counter(unit for task in selected for unit in task_projects[task.id])
    kind_counts = Counter(task.structural_signal.kind for task in selected)
    remaining = [task for task in ranked if task not in selected]
    while remaining and len(selected) < limit:
        # Soft diversity within the same evidence tier, without per-app quotas
        # or sacrificing a stronger opportunity to a weaker one. Already
        # covered signal kinds rank after uncovered ones, so documentary and
        # structural probes coexist instead of one kind evicting the other.
        task = min(remaining, key=lambda item: (
            *candidate_rank(item)[:2], min((coverage_counts[unit] for unit in task_projects[item.id]), default=0),
            kind_counts[item.structural_signal.kind],
            preferences.get(item.id, len(preferences)), *candidate_rank(item)[2:]))
        selected.append(task)
        coverage_counts.update(task_projects[task.id])
        kind_counts[task.structural_signal.kind] += 1
        remaining.remove(task)
    return selected


def planning_diagnostics(inventory, menu, selected, model_selected, *, maximum=12):
    projects = inventory.get("_task_projects", {})

    def counts(tasks):
        return Counter(project for task in tasks for project in projects[task.id])
    menu_counts, final_counts, model_counts = counts(menu), counts(selected), counts(model_selected)
    rows = []
    for original in inventory.get("project_coverage", []):
        row = dict(original)
        project = row["project_id"]
        row.update(menu_candidates=menu_counts[project], selected=final_counts[project], model_selected=model_counts[project])
        row["internal_selected"] = sum(project in projects[task.id] and task.scope_kind == "internal" for task in selected)
        row["internal_menu_candidates"] = sum(project in projects[task.id] and task.scope_kind == "internal" for task in menu)
        row["integration_selected"] = sum(project in projects[task.id] and task.scope_kind != "internal" for task in selected)
        row["candidates_omitted"] = row["candidates_after_dedup"] - row["menu_candidates"]
        if not row["eligible_files"]:
            status = "no_eligible_files"
        elif not row["candidates_after_dedup"]:
            status = "no_indexed_opportunities"
        elif not row["menu_candidates"]:
            status = "menu_or_context_budget"
        elif row["selected"]:
            status = "selection_rebalanced" if not row["model_selected"] else "selected"
        elif not model_selected:
            status = "model_abstained_or_unavailable"
        else:
            status = "selection_budget" if len(selected) >= maximum else "selection_bias"
        row["selection_status"] = status
        rows.append(row)
    eligible_projects = sum(row["menu_candidates"] > 0 for row in rows)
    model_projects = sum(row["model_selected"] > 0 for row in rows)
    selected_ids, model_ids = {task.id for task in selected}, {task.id for task in model_selected}
    return {"by_project": rows,
        "applications_detected": [{key: row[key] for key in ("project_id", "root", "eligible_files")} for row in rows],
        "selection_bias_detected": bool(model_selected) and model_projects < min(maximum, eligible_projects),
        "selection_rebalanced": selected_ids != model_ids,
        "selection_reordered": selected_ids == model_ids and [task.id for task in selected] != [task.id for task in model_selected],
        "selection_added_ids": sorted(selected_ids - model_ids), "selection_removed_ids": sorted(model_ids - selected_ids),
        "selected_by_scope": dict(Counter(task.scope_kind for task in selected)),
        "selected_by_type": dict(Counter(task.structural_signal.kind for task in selected)),
        "opportunities": inventory.get("opportunity_diagnostics", {}),
        "integrations": inventory.get("integration_diagnostics", {}),
        "documentation": documentary_diagnostics(inventory, menu, selected)}


def prepare_planning(snapshot, request, *, limit, check, config=None, character_limit=150_000):
    """Keep source bodies, comments, narrative signals and normative guesses out."""
    check()
    config = config or BoundaryConfig()
    all_files = {file.id: file for file in snapshot.files}
    all_symbols = {symbol.id: symbol for symbol in snapshot.symbols}
    selectors = [value.replace("\\", "/").rstrip("/") or "." for value in (
        request.targets or [value for item in request.follow_up for value in [*item.paths, *item.subject_ids]])]
    test_paths = {path for testing in snapshot.testing for path in testing.file_paths}

    def explicitly_requested(file):
        return any(value in (file.id, file.path, file.module_name)
            or (value in all_symbols and all_symbols[value].file_id == file.id)
            or (nonproduction_path(value) and file.path.startswith(value + "/")) for value in selectors)

    files = {key: file for key, file in all_files.items()
        if not (file.path in test_paths or nonproduction_path(file.path)) or explicitly_requested(file)}
    symbols = {key: symbol for key, symbol in all_symbols.items() if symbol.file_id in files}
    owners = {**{key: key for key in files}, **{key: s.file_id for key, s in symbols.items()}}

    def project_for(file):
        roots = [project for project in snapshot.projects
            if project.path == "." or file.path.startswith(project.path.rstrip("/") + "/")]
        return max(roots, key=lambda project: len(project.path) if project.path != "." else 0).id if roots else file.project_id

    file_projects = {key: project_for(file) for key, file in all_files.items()}

    def selected(file):
        return not selectors or any(
            value in (file.id, file.path, file.module_name, ".")
            or file.path.startswith(value.rstrip("/") + "/")
            or (value in all_symbols and all_symbols[value].file_id == file.id)
            for value in selectors
        )

    seeds = {key for key, file in files.items() if selected(file)}
    groups = {key: (file_projects[key], str(PurePosixPath(file.path).parent)) for key, file in files.items()}
    edges = []
    unresolved = 0
    for relation in snapshot.relationships:
        check()
        source, target = owners.get(relation.source_id), owners.get(relation.target_id)
        if source in seeds and relation.resolution in {"unresolved", "dynamic"}:
            unresolved += 1
        if source and target and source != target and relation.resolution == "internal":
            edges.append((relation, source, target))
    # Counts use unique module pairs, not many imports of the same module.
    directions = defaultdict(set)
    runtime_directions = defaultdict(set)
    type_directions = defaultdict(set)
    by_direction = defaultdict(list)
    for relation, source, target in edges:
        check()
        by_direction[groups[source], groups[target]].append((relation, source, target))
        if groups[source] != groups[target]:
            directions[groups[source], groups[target]].add((source, target))
            family = type_directions if relation.kind == "type_only" else runtime_directions
            family[groups[source], groups[target]].add((source, target))
    relevant = [(r, a, b) for r, a, b in edges if a in seeds or b in seeds]
    relevant.sort(key=lambda edge: (files[edge[1]].path, files[edge[2]].path, edge[0].id))
    limitations = [
        "Indexed dependencies are structural navigation, not proof of runtime coupling or an architectural rule.",
        "Directory/module groups are provisional; names alone do not establish boundaries.",
        "The accessible symbol index does not expose an exhaustive export/visibility map; public entrypoint labels may be inferred.",
    ]
    if unresolved:
        limitations.append(f"{unresolved} scoped dynamic/unresolved relationships cannot be resolved by this index.")
    if snapshot.coverage.unsupported_source_languages or snapshot.coverage.issues:
        limitations.append("Snapshot coverage is incomplete (unsupported languages or extraction issues).")
    if selectors and not seeds:
        limitations.append("No accessible indexed file matches the requested scope; no substitute scope was invented.")
    if not relevant:
        limitations.append("No resolved inter-module dependencies are available in scope. Structural tools query the same index; missing edges are not proof of independence.")

    candidates = []
    signatures = set()

    def add(kind, priority, selected_edges, observed, inference, *, scope_ids=(), entrypoints=(), basis="indexed", support_symbols=()):
        check()
        ids = list(dict.fromkeys([*scope_ids, *(item for _, a, b in selected_edges for item in (a, b))]))
        paths = [files[key].path for key in ids[:12]]
        if not paths:
            return
        signature = (kind, tuple(sorted(paths))) if kind in {"cycle", "discovery"} else (
            kind, *sorted((selected_edges[0][1], selected_edges[0][2])))
        if signature in signatures:
            return
        signatures.add(signature)
        retained_ids = set(ids[:12])
        retained_edges = [edge for edge in selected_edges if edge[1] in retained_ids and edge[2] in retained_ids][:12]
        refs = [StructuralRelationship(id=r.id, source_id=r.source_id, target_id=r.target_id,
            source_path=files[a].path, target_path=files[b].path, kind=r.kind)
            for r, a, b in retained_edges]
        symbol_ids = sorted({*support_symbols, *(key for r, _, _ in retained_edges
            for key in (r.source_id, r.target_id) if key in symbols)})
        interaction = f"{refs[0].source_path} → {refs[0].target_path} ({refs[0].kind})" if refs else paths[0]
        questions = {
            "discovery": f"Which declarations and directed dependency endpoints can be established for {paths[0]}, and which missing relationships require source inspection?",
            "cycle": f"Which mechanisms connect the indexed cyclic module group seeded by {', '.join(paths[:3])}, and do declarations or actual usage support a boundary that the cycle crosses?",
            "direction": f"Does the less frequent dependency {interaction} follow the code-supported direction and interface boundary, or is there a justified exception?",
            "encapsulation": f"Does {interaction} bypass a meaningful public contract, or is it a legitimate alternative access path?",
            "component_boundary": f"What mechanism connects {interaction}, and does code or actual usage support a relevant boundary, or is this an ordinary legitimate interaction?",
        }
        needed = ["Source and target declarations and actual dependency mechanism",
            "Technical boundary declarations and supported dependency directions, if any",
            "Comparable interactions, public access paths and legitimate exceptions",
            "Material limitations when an endpoint or boundary cannot be established"]
        if kind == "cycle":
            needed.append("Cycle edges, conditional/type-only imports and the extent of the strongly connected component")
        elif kind == "direction":
            needed.append("The cited reverse-direction comparisons and why the directions differ")
        candidates.append(BoundaryInvestigation(
            id=create_identifier("investigation", snapshot.repository.snapshot_hash, kind, *sorted(paths)),
            priority=priority, scope=paths,
            structural_signal=StructuralSignal(kind=kind, observed=observed, inference=inference, basis=basis,
                relationships=refs, symbol_ids=symbol_ids, entrypoint_ids=list(entrypoints)),
            question=questions[kind], evidence_needed=needed,
            investigation_strategy=[StructuralQuery(tool="find_symbols", arguments={"file_path": paths[0], "limit": 10}),
                StructuralQuery(tool="list_relationships", arguments=(
                    {"source_id": refs[0].source_id, "target_id": refs[0].target_id, "kind": refs[0].kind, "limit": 10}
                    if refs else {"source_id": ids[0], "limit": 10}))],
            completion_condition="The scoped interaction and relevant boundary have been examined, including legitimate explanations, or material limitations are documented; finding a defect is not required.",
        ))

    # Reuse the existing SCC algorithm over resolved file projections. Do not
    # reuse naming-based architecture signals from repository analysis.
    context = AnalysisContext(tuple(files.values()), [])
    context.relationships = [r.model_copy(update={"source_id": a, "target_id": b}) for r, a, b in edges]
    cycles = find_import_cycles(context)
    context.relationships = [r.model_copy(update={"source_id": a, "target_id": b})
        for r, a, b in edges if r.kind != "type_only"]
    runtime_cycles = [set(component) for component in find_import_cycles(context)]
    cycle_membership = {member: index for index, component in enumerate(cycles) for member in component}
    cycle_relationships = defaultdict(list)
    for edge in edges:
        _, source, target = edge
        if source in cycle_membership and cycle_membership[source] == cycle_membership.get(target):
            cycle_relationships[cycle_membership[source]].append(edge)
    for index, component in enumerate(cycles):
        check()
        members = set(component)
        if members & seeds:
            cycle_edges = sorted(cycle_relationships[index], key=lambda edge: (edge[1] not in seeds, edge[0].id))
            runtime_cycle = any(cycle <= members for cycle in runtime_cycles)
            type_count = sum(edge[0].kind == "type_only" for edge in cycle_edges)
            add("cycle", "medium" if runtime_cycle else "low", cycle_edges,
                [f"The resolved module graph contains a strongly connected component of {len(component)} modules; displayed endpoints are bounded seeds, not necessarily the entire cycle.",
                    f"Indexed type_only edges={type_count}; a cycle remains without type_only edges={runtime_cycle}. Conditional imports may still be present."],
                "Potentially independent modules may be involved; conditional/type-only edges and legitimacy require inspection.",
                basis="corroborated" if runtime_cycle else "inferred")

    # A rare reverse direction needs multiple distinct observed module pairs;
    # no architecture vocabulary or folder-name convention is involved.
    relevant_pairs = {}
    for edge in relevant:
        relevant_pairs.setdefault((groups[edge[1]], groups[edge[2]], edge[0].kind == "type_only"), edge)
    for (source_group, target_group, _), edge in sorted(relevant_pairs.items(), key=lambda item: item[0][2]):
        check()
        family = type_directions if edge[0].kind == "type_only" else runtime_directions
        forward = family[source_group, target_group]
        reverse = family[target_group, source_group]
        if source_group != target_group and len(reverse) >= 3 and len(reverse) >= 3 * len(forward):
            type_only = edge[0].kind == "type_only"
            comparable = [item for item in by_direction[target_group, source_group]
                if (item[0].kind == "type_only") == type_only][:3]
            add("direction", "low" if type_only else "medium", [edge, *comparable],
                [f"Distinct module-pair counts between these directory/project groups ({'type_only' if type_only else 'non-type_only'}): this direction={len(forward)}, reverse={len(reverse)}."],
                "A less frequent direction is observable, but a required direction is not established.")

    # An indexed public-API candidate plus multiple observed callers is stronger
    # than a name alone, but the API label can still be inferred by the extractor.
    callers_by_file = defaultdict(list)
    for edge in edges:
        callers_by_file[edge[2]].append(edge)
    public = defaultdict(list)
    for entry in snapshot.entrypoints:
        check()
        if entry.kind == "public_api" and entry.file_id in files:
            group = groups[entry.file_id]
            callers = [edge for edge in callers_by_file[entry.file_id] if groups[edge[1]] != group]
            by_caller = {edge[1]: edge for edge in callers}
            if len(by_caller) >= 2:
                public[group].append((entry, list(by_caller.values())[:2]))
    encapsulation_pairs = set()
    for edge in relevant:
        check()
        _, a, b = edge
        pair = (groups[a], groups[b])
        if pair in encapsulation_pairs:
            continue
        for entry, callers in public[groups[b]]:
            entry_file = entry.file_id
            if entry_file == b or groups[entry_file] != groups[b] or groups[a] == groups[b]:
                continue
            encapsulation_pairs.add(pair)
            add("encapsulation", "low" if edge[0].kind == "type_only" or entry.detection == "inferred" else "medium", [edge, *callers],
                [f"An indexed public_api candidate (detection={entry.detection}) has multiple external callers; another interaction targets a different module in the same directory/project group."],
                "The public API label may itself be inferred. Whether the alternate path bypasses a meaningful interface is an open question.",
                entrypoints=(entry.id,), basis="inferred" if entry.detection == "inferred" else "corroborated")
            break

    # Internal component boundaries need actual module ownership/declarations or
    # repeated indexed interactions, not cycles/anomalies or folder names alone.
    # A speculative public-API label must not suppress a better grounded probe.
    represented = {ref.id for task in candidates
        if task.structural_signal.kind != "encapsulation" or task.structural_signal.basis != "inferred"
        for ref in task.structural_signal.relationships}
    represented_boundaries = {frozenset((groups[owners[ref.source_id]], groups[owners[ref.target_id]]))
        for task in candidates if task.structural_signal.basis != "inferred"
        for ref in task.structural_signal.relationships}
    declarations = defaultdict(list)
    for symbol in symbols.values():
        if symbol.kind in {"class", "function", "interface", "method", "type_alias"}:
            declarations[symbol.file_id].append(symbol.id)
    boundary_filter_counts = Counter()
    seen_groups = set()
    for edge in relevant:
        check()
        r, a, b = edge
        pair = (groups[a], groups[b])
        if r.id in represented or pair in seen_groups or frozenset(pair) in represented_boundaries:
            continue
        cross_application = file_projects[a] != file_projects[b]
        declared_endpoints = bool(declarations[a] and declarations[b])
        repeated_interactions = len(directions[pair]) >= 2
        if not cross_application and (groups[a] == groups[b] or not (declared_endpoints or repeated_interactions)):
            boundary_filter_counts[file_projects[a]] += 1
            continue
        seen_groups.add(pair)
        boundary_edges = [edge]
        if not cross_application and not declared_endpoints:
            # Preserve the independent indexed interaction that qualified this
            # seed, rather than reporting a count with only one citation.
            comparison = next(item for item in by_direction[pair] if (item[1], item[2]) != (a, b))
            boundary_edges.append(comparison)
        add("component_boundary", "medium" if r.kind != "type_only" else "low", boundary_edges,
            ["A resolved code dependency directly crosses indexed application roots." if cross_application else
                f"A resolved dependency joins different module groups; declarations at both endpoints={declared_endpoints}; distinct module-pair interactions={len(directions[pair])}."],
            "Module grouping is a provisional boundary, not a rule. Inspect the code-supported contract, access path and dependency direction; an ordinary legitimate interaction is a valid outcome.",
            support_symbols=[*declarations[a][:1], *declarations[b][:1]])
    # Missing import edges alone are not an architectural opportunity. Probe
    # integrations only when actual client/endpoint declarations provide a seed.
    integration_tasks, integration_diagnostics = discover_integrations(
        snapshot, files, file_projects, seeds, config, check, character_limit)
    candidates.extend(integration_tasks)
    documentary_tasks, document_claims, documentary_status, documentary_limits = prepare_documentation(
        snapshot, request, files, seeds, file_projects, check=check)
    candidates.extend(documentary_tasks)
    limitations.extend(documentary_limits)
    limitations.append("Import absence does not exclude HTTP/RPC/WebSocket integration. Lightweight discovery supports literal clients/routes/listeners only; dynamic wiring, mounts and unscanned files remain unresolved.")

    path_projects = {file.path: file_projects[key] for key, file in files.items()}
    scoped_projects = {file_projects[key] for key in seeds}

    def focus_paths(task):
        refs = task.structural_signal.relationships
        return task.scope if task.structural_signal.kind == "cycle" or not refs else [refs[0].source_path, refs[0].target_path]

    candidates = [task if task.project_ids else task.model_copy(update={
        "project_ids": sorted({path_projects[path] for path in focus_paths(task)}),
        "scope_kind": "inter_application" if len({path_projects[path] for path in focus_paths(task)}) > 1 else "internal",
    }) for task in candidates]
    task_projects = {task.id: sorted(set(task.project_ids) & scoped_projects) for task in candidates}
    generated = candidates
    candidates, semantic_keys, covered_relations = [], set(), set()
    for task in sorted(generated, key=candidate_rank):
        check()
        focus = focus_paths(task)
        # Deduplicate the actual boundary/primary relation, not every relation
        # involving the same directory pair or a shared component.
        links = task.structural_signal.integration_links
        if task.structural_signal.kind == "documented_boundary":
            # A documentary objective is distinct from a structural probe of the
            # same files/edge. Its mechanism/scope was grouped before this stage.
            candidates.append(task)
            continue
        key = ("integration", tuple(link.id for link in links)) if links else ("modules", frozenset(focus))
        refs = task.structural_signal.relationships
        if key in semantic_keys or (refs and task.structural_signal.kind != "cycle" and refs[0].id in covered_relations):
            continue
        semantic_keys.add(key)
        covered_relations.update(ref.id for ref in refs if task.structural_signal.kind == "cycle" or ref == refs[0])
        candidates.append(task)
    candidates, document_claims = link_structural_opportunities(candidates, document_claims, check)
    coverage_units = {task.id: (["integration:" + ":".join(task.project_ids)] if task.scope_kind == "inter_application"
        else ["internal:" + project for project in task_projects[task.id]]) for task in candidates}
    menu = balance_candidates(candidates, coverage_units, limit)
    if len(candidates) > len(menu):
        limitations.append(f"Candidate menu bounded: {len(candidates) - len(menu)} opportunities omitted; not an exhaustive plan.")
    seed_files = [files[key] for key in sorted(seeds, key=lambda key: files[key].path)]
    ancestors = {str(parent) for file in seed_files for parent in PurePosixPath(file.path).parents}
    project_ids = {file_projects[file.id] for file in seed_files}
    all_owners = {**{key: key for key in all_files}, **{key: symbol.file_id for key, symbol in all_symbols.items()}}
    scoped_all = {key for key, file in all_files.items() if selected(file)}
    roster = {file_projects[key] for key in scoped_all}
    project_records = {project.id: project for project in snapshot.projects}
    project_coverage = []
    for project in sorted(roster):
        check()
        project_files = {key for key in seeds if file_projects[key] == project}
        project_edges = [edge for edge in relevant if project in {file_projects[edge[1]], file_projects[edge[2]]}]
        project_paths = {files[key].path for key in project_files}
        unresolved_edges = sum(owners.get(relation.source_id) in project_files
            and relation.resolution in {"unresolved", "dynamic"} for relation in snapshot.relationships)
        partial = any(issue.path in project_paths for issue in snapshot.coverage.issues)
        partial |= any(files[key].language in snapshot.coverage.unsupported_source_languages for key in project_files)
        project_coverage.append({"project_id": project, "root": project_records[project].path if project in project_records else project,
            "eligible_files": len(project_files),
            "excluded_nonproduction_files": sum(key not in files and file_projects[key] == project for key in scoped_all),
            "eligible_relationships": len(project_edges),
            "unresolved_relationships": unresolved_edges,
            "type_only_relationships": sum(edge[0].kind == "type_only" for edge in project_edges),
            "non_type_only_relationships": sum(edge[0].kind != "type_only" for edge in project_edges),
            "index_status": ("partial" if partial else "relationships_available" if project_edges
                else "unresolved_relationships" if unresolved_edges else "no_indexed_relationships"),
            "candidates_generated": sum(project in task_projects[task.id] for task in generated),
            "internal_candidates_generated": sum(project in task_projects[task.id] and task.scope_kind == "internal" for task in generated),
            "internal_candidates_after_dedup": sum(project in task_projects[task.id] and task.scope_kind == "internal" for task in candidates),
            "component_seeds_without_boundary_support": boundary_filter_counts[project],
            "candidates_after_dedup": sum(project in task_projects[task.id] for task in candidates),
            "candidates_deduplicated": sum(project in task_projects[task.id] for task in generated)
                - sum(project in task_projects[task.id] for task in candidates)})
    inventory = {
        "counts": {"files": len(seeds), "symbols": sum(s.file_id in seeds for s in symbols.values()),
            "resolved_relationships": len(relevant), "unresolved_relationships": unresolved,
            "type_only_relationships": sum(edge[0].kind == "type_only" for edge in relevant),
            "excluded_nonproduction_files": sum(key not in files for key in scoped_all)},
        "project_coverage": project_coverage,
        "_task_projects": task_projects,
        "_coverage_units": coverage_units,
        "_initial_menu_size": len(menu),
        "integration_diagnostics": integration_diagnostics,
        "_document_claims": document_claims,
        "_documentary_candidates": candidates,
        "_initial_document_claim_ids": {key for task in menu for key in task.document_claim_ids},
        "documentary_diagnostics": documentary_status,
        "opportunity_diagnostics": {"generated_by_type": dict(Counter(task.structural_signal.kind for task in generated)),
            "generated_by_scope": dict(Counter(task.scope_kind for task in generated)),
            "deduplicated": len(generated) - len(candidates),
            "quality_discarded_relationship_seeds": sum(boundary_filter_counts.values()),
            "menu_budget_omitted": len(candidates) - len(menu),
            "internal_relationships": sum(file_projects[a] == file_projects[b] for _, a, b in relevant),
            "cross_application_imports": sum(file_projects[a] != file_projects[b] for _, a, b in relevant)},
        "_eligible_file_ids": set(files),
        "_eligible_relationship_ids": {r.id for r in snapshot.relationships if owners.get(r.source_id)
            and (r.target_id not in all_owners or owners.get(r.target_id))},
        "files": [{"id": f.id, "path": f.path, "module": f.module_name, "language": f.language} for f in seed_files[:limit]],
        "directories": [{"id": directory.id, "path": directory.path, "kind": directory.kind}
            for directory in snapshot.directories if directory.path in ancestors][:limit],
        "projects": [{"id": project.id, "path": project.path, "ecosystem": project.ecosystem,
            "manifest_paths": list(project.manifest_paths[:3])} for project in snapshot.projects if project.id in project_ids][:limit],
        "symbols": [{"id": s.id, "file_id": s.file_id, "name": s.name, "kind": s.kind}
            for s in sorted(symbols.values(), key=lambda s: s.id) if s.file_id in seeds][:limit],
        "groups": [{"project_id": project, "directory": directory, "module_count": count}
            for (project, directory), count in Counter(groups[key] for key in seeds).most_common(limit)],
        "dependency_directions": [{"source_group": a, "target_group": b, "module_pairs": len(pairs),
            "non_type_only_module_pairs": len(runtime_directions[a, b]), "type_only_module_pairs": len(type_directions[a, b])}
            for (a, b), pairs in sorted(directions.items(), key=lambda item: (-len(item[1]), item[0]))
            if any(a in seeds or b in seeds for a, b in pairs)][:limit],
        "limitations": limitations,
    }
    return menu, inventory, limitations
