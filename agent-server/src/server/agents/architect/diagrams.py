"""Assemble Mermaid diagrams from derived structure plus model grouping.

Pure functions: same inputs, same text, every run. Nothing here calls a
model. Names and membership come from the architect's grouping judgment
(containers for files, role groups for third-party dependencies); every
arrow comes from the dependency graph, every interface from the collected
symbols. Anything that cannot be derived is left out rather than invented:
a container uses an external group only when some member file really imports
some member dependency, and business actors do not appear at all.
"""

import re

from ..analyzer.facts import specifier_head

# A whole-project diagram past this is spaghetti, not documentation. Kept
# counts are deterministic (highest degree, then alphabetical), and the block
# carries a `truncated` comment when the cap bites.
MAX_DIAGRAM_NODES = 40
MAX_DIAGRAM_EDGES = 60

# Provided interfaces listed per component node. UML would draw lollipops;
# Mermaid has no such shape, so they ride along in the node label instead.
MAX_PROVIDED_SYMBOLS = 5
MAX_EXTERNAL_MEMBERS = 8
MAX_LABEL_CHARS = 80


def sanitize_id(name: str, taken: set[str]) -> str:
    """A Mermaid-safe node id, unique within the diagram.

    Paths carry `/.-` which Mermaid reads as syntax, so everything outside
    `[A-Za-z0-9_]` becomes `_`. Collisions take `_2`, `_3`, ... in encounter
    order, which keeps the output deterministic.
    """
    base = re.sub(r"[^A-Za-z0-9_]", "_", name).strip("_") or "node"
    candidate = base
    counter = 2

    while candidate in taken:
        candidate = f"{base}_{counter}"
        counter += 1

    taken.add(candidate)
    return candidate


def quote(label: str) -> str:
    """A node label that survives Mermaid parsing."""
    return label.replace('"', "'")


def _external_label(name: str, members: list[str]) -> str:
    """Roles are dependencies, not independently deployed external systems."""
    shown = sorted(set(members))[:MAX_EXTERNAL_MEMBERS]
    labels = [quote(value[:MAX_LABEL_CHARS]) for value in [name, *shown]]
    if len(set(members)) > len(shown):
        labels.append(f"+{len(set(members)) - len(shown)} more")
    return "External dependencies<br/>" + "<br/>".join(labels)


def _limit_nodes(
    nodes: set[str], links: set[tuple[str, str]],
) -> tuple[set[str], bool]:
    """Keep high-degree nodes first, with stable alphabetical tie breaks."""
    degree = dict.fromkeys(nodes, 0)
    for source, target in links:
        if source in degree:
            degree[source] += 1
        if target in degree:
            degree[target] += 1
    ordered = sorted(nodes, key=lambda node: (-degree[node], node))
    return set(ordered[:MAX_DIAGRAM_NODES]), len(nodes) > MAX_DIAGRAM_NODES


def build_diagrams(
    *,
    system_name: str,
    edges: list[dict],
    file_symbols: dict[str, list[str]],
    containers: list[dict],
    externals: list[dict],
    components: list[dict],
    entrypoints: list[str],
    cycles: list[list[str]],
    third_party: list[str],
) -> dict:
    """Two Mermaid blocks: containers (C4 L2) and components (UML-flavoured).

    Returns {"containers": str, "components": str, "truncated": bool}. Empty
    inputs yield empty strings, matching the schema defaults.
    """
    containers_block, truncated_containers = _containers_diagram(
        system_name, edges, containers, externals, third_party
    )
    components_block, truncated_components = _components_diagram(
        edges, file_symbols, containers, components, entrypoints, cycles
    )
    return {
        "containers": containers_block,
        "components": components_block,
        "truncated": truncated_containers or truncated_components,
    }


def _internal_edges(edges: list[dict]) -> set[tuple[str, str]]:
    """Resolved file-to-file imports, deduplicated, self-loops dropped."""
    found: set[tuple[str, str]] = set()

    for edge in edges:
        if not isinstance(edge, dict):
            continue
        source = edge.get("source")
        target = edge.get("target")
        if (
            isinstance(source, str) and isinstance(target, str)
            and source and target and source != target
        ):
            found.add((source, target))

    return found


def _external_uses(edges: list[dict]) -> set[tuple[str, str]]:
    """(source file, dependency head) for unresolved external imports.

    Same head convention as the third-party listing, so these join cleanly
    with the model-grouped external members.
    """
    found: set[tuple[str, str]] = set()

    for edge in edges:
        if not isinstance(edge, dict):
            continue
        if edge.get("resolved"):
            continue
        source = edge.get("source")
        head = specifier_head(str(edge.get("specifier") or ""))
        if isinstance(source, str) and source and head:
            found.add((source, head))

    return found


def _containers_diagram(
    system_name: str,
    edges: list[dict],
    containers: list[dict],
    externals: list[dict],
    third_party: list[str],
) -> tuple[str, bool]:
    if not containers:
        return "", False

    containers = sorted(containers, key=lambda container: container["name"])
    taken: set[str] = set()
    ids = {c["name"]: sanitize_id(f"container_{c['name']}", taken) for c in containers}
    member_of = {
        path: c["name"]
        for c in containers
        for path in c.get("files", [])
        if isinstance(path, str)
    }

    links: set[tuple[str, str]] = set()
    for source, target in sorted(_internal_edges(edges)):
        a, b = member_of.get(source), member_of.get(target)
        if a and b and a != b:
            links.add((a, b))

    # External groups the model named, with only the members the collection
    # knows. Container -> group arrows are derived: some member file really
    # imports some member dependency.
    known_deps = set(third_party or [])
    groups = {
        group["name"]: [m for m in group.get("members", []) if m in known_deps]
        for group in externals
        if isinstance(group, dict) and str(group.get("name", "")).strip()
    }
    groups = {name: members for name, members in groups.items() if members}
    # Assign repeated dependencies to the alphabetically first role, rather
    # than depending on model output order. Preserve ungrouped dependencies.
    member_group: dict[str, str] = {}
    for name in sorted(groups):
        for dep in sorted(set(groups[name])):
            member_group.setdefault(dep, name)
    groups = {
        name: sorted(dep for dep, owner in member_group.items() if owner == name)
        for name in sorted(groups)
    }
    groups = {name: members for name, members in groups.items() if members}
    ungrouped = sorted(known_deps - member_group.keys())
    if ungrouped:
        fallback = "third-party"
        groups.setdefault(fallback, []).extend(ungrouped)
        member_group.update(dict.fromkeys(ungrouped, fallback))

    ext_ids = {
        name: sanitize_id(f"ext_{name}", taken) for name in sorted(groups)
    }

    external_links: set[tuple[str, str]] = set()
    for source, dep in sorted(_external_uses(edges)):
        container, group = member_of.get(source), member_group.get(dep)
        if container and group:
            external_links.add((container, group))

    all_links = {
        (ids[source], ids[target]) for source, target in links
    } | {
        (ids[source], ext_ids[target]) for source, target in external_links
    }
    kept, nodes_truncated = _limit_nodes(set(ids.values()) | set(ext_ids.values()), all_links)
    kept_links = sorted((a, b) for a, b in all_links if a in kept and b in kept)
    truncated = nodes_truncated or len(kept_links) > MAX_DIAGRAM_EDGES
    boundary_id = sanitize_id("system_boundary", taken)
    lines = ["flowchart LR", f'    subgraph {boundary_id}["{quote(system_name)}"]']
    for container in containers:
        if ids[container["name"]] in kept:
            lines.append(f"        {ids[container['name']]}[[\"{quote(container['name'])}\"]]")
    lines.append("    end")
    for name in sorted(groups):
        ext_id = ext_ids[name]
        if ext_id not in kept:
            continue
        label = _external_label(name, groups[name])
        lines.append(f"    {ext_id}([\"{label}\"])")
        lines.append(f"    style {ext_id} stroke-dasharray: 5 5")
    if ungrouped:
        lines.append("    %% ungrouped dependencies collected into third-party")
    for source, target in kept_links[:MAX_DIAGRAM_EDGES]:
        lines.append(f"    {source} -->|uses| {target}")
    if truncated:
        lines.append(
            f"    %% truncated: showing {len(kept)} of {len(ids) + len(ext_ids)} nodes; "
            f"{min(len(kept_links), MAX_DIAGRAM_EDGES)} of {len(all_links)} relations"
        )
    lines.insert(1, f"    %% {quote(system_name)}: containers and their real imports")
    return "\n".join(lines) + "\n", truncated


def _components_diagram(
    edges: list[dict],
    file_symbols: dict[str, list[str]],
    containers: list[dict],
    components: list[dict],
    entrypoints: list[str],
    cycles: list[list[str]],
) -> tuple[str, bool]:
    paths = sorted({
        str(item.get("path", "")).strip()
        for item in components
        if isinstance(item, dict) and str(item.get("path", "")).strip()
    })
    if not paths:
        return "", False

    in_cycle: set[tuple[str, str]] = set()
    for group in cycles:
        if not isinstance(group, list):
            continue
        members = [path for path in group if isinstance(path, str)]
        for first in members:
            for second in members:
                if first != second:
                    in_cycle.add((first, second))
    entries = set(entrypoints or [])

    taken: set[str] = set()
    ids = {path: sanitize_id(f"comp_{path}", taken) for path in paths}

    links = sorted({
        (source, target) for source, target in _internal_edges(edges)
        if source in ids and target in ids
    })
    kept, nodes_truncated = _limit_nodes(set(paths), set(links))
    total_links = len(links)
    total_nodes = len(paths)
    paths = [path for path in paths if path in kept]
    links = [(source, target) for source, target in links if source in kept and target in kept]
    truncated = nodes_truncated or len(links) > MAX_DIAGRAM_EDGES
    cycle_edges = {
        index for index, (source, target) in enumerate(links[:MAX_DIAGRAM_EDGES])
        if (source, target) in in_cycle
    }

    lines = ["flowchart LR"]
    for path in paths:
        provided = [s for s in (file_symbols.get(path) or []) if s][:MAX_PROVIDED_SYMBOLS]
        label = quote(path)
        if provided:
            label += "<br/>+" + "<br/>+".join(quote(symbol) for symbol in provided)
        if path in entries:
            lines.append(f"    {ids[path]}[/\"{label}\"/]")
        else:
            lines.append(f"    {ids[path]}[[\"{label}\"]]")
    for index, (source, target) in enumerate(links[:MAX_DIAGRAM_EDGES]):
        lines.append(f"    {ids[source]} -->|imports| {ids[target]}")
    if cycle_edges:
        lines.append(f"    linkStyle {','.join(str(i) for i in sorted(cycle_edges))} stroke:#b91c1c,stroke-width:2px")
    if truncated:
        lines.append(
            f"    %% truncated: showing {len(paths)} of {total_nodes} nodes; "
            f"{min(len(links), MAX_DIAGRAM_EDGES)} of {total_links} relations"
        )
    return "\n".join(lines) + "\n", truncated
