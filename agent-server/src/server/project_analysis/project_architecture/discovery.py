"""Connected investigation hints from retained structural facts, never classifications."""

import re
from pathlib import PurePosixPath


def connected_candidates(snapshot, implementation):
    files = {
        source.id: source for sources in implementation.values() for source in sources
    }
    symbols = {}
    owners = {}
    for symbol in snapshot.symbols:
        owners[symbol.id] = symbol.file_id
        symbols.setdefault(symbol.file_id, []).append(symbol)

    def role(source):
        path = PurePosixPath(source.path)
        tokens = set(re.split(r"[._-]", path.name.lower()))
        declarations = symbols.get(source.id, [])
        if "port" in tokens or any(
            "ABC" in symbol.base_names
            or (
                symbol.name.startswith("I")
                and len(symbol.name) > 1
                and symbol.name[1].isupper()
                and symbol.kind in {"class", "interface"}
            )
            for symbol in declarations
        ):
            return "port"
        if (
            tokens.intersection({"repository", "adapter", "exporter"})
            or "infrastructure" in path.parts
        ):
            return "adapter"
        if (
            tokens.intersection({"service", "handler", "usecase"})
            or "use_cases" in path.parts
        ):
            return "use_case"
        if tokens.intersection({"bootstrap", "module", "container"}):
            return "composition"
        return None

    roles = {identifier: role(source) for identifier, source in files.items()}
    edges = set()
    implementations = set()
    for relation in snapshot.relationships:
        if relation.resolution != "internal" or relation.kind not in {
            "import",
            "from_import",
            "inherits",
            "implements",
            "reexport",
        }:
            continue
        origin = owners.get(relation.source_id, relation.source_id)
        target = owners.get(relation.target_id, relation.target_id)
        if origin in files and target in files and origin != target:
            edges.add((origin, target))
            if relation.kind in {"inherits", "implements"}:
                implementations.add((origin, target))
    outgoing = {identifier: set() for identifier in files}
    incoming = {identifier: set() for identifier in files}
    for origin, target in edges:
        outgoing[origin].add(target)
        incoming[target].add(origin)

    candidates = []
    for port in sorted(files, key=lambda identifier: files[identifier].path):
        if roles[port] != "port":
            continue
        callers = sorted(
            (
                identifier
                for identifier in incoming[port]
                if roles[identifier] == "use_case"
            ),
            key=lambda identifier: files[identifier].path,
        )
        adapters = sorted(
            (
                identifier
                for identifier in incoming[port]
                if roles[identifier] == "adapter"
                and (identifier, port) in implementations
            ),
            key=lambda identifier: files[identifier].path,
        )
        if not callers or not adapters:
            continue
        caller = callers[0]
        # Prefer an adapter whose composition can also be followed in source.
        adapter = max(
            adapters,
            key=lambda identifier: sum(
                roles[item] == "composition" for item in incoming[identifier]
            ),
        )
        composition = sorted(
            (
                identifier
                for identifier in incoming[adapter]
                if roles[identifier] == "composition"
            ),
            key=lambda identifier: files[identifier].path,
        )
        members = [(caller, "use_case"), (port, "port"), (adapter, "adapter")]
        if composition:
            members.append((composition[0], "composition"))
        member_ids = {identifier for identifier, _ in members}
        candidates.append(
            {
                "project_id": files[port].project_id,
                "files": [
                    {
                        "file_id": identifier,
                        "path": files[identifier].path,
                        "role_hint": hint,
                        "symbols": [
                            {
                                "name": symbol.name,
                                "start_line": symbol.start_line,
                                "end_line": symbol.end_line,
                            }
                            for symbol in sorted(
                                symbols.get(identifier, []),
                                key=lambda item: (
                                    item.kind not in {"class", "interface"},
                                    item.start_line,
                                ),
                            )
                            if symbol.parent_symbol_id is None
                        ][:2],
                    }
                    for identifier, hint in members
                ],
                "dependency_hints": [
                    {
                        "source_path": files[origin].path,
                        "target_path": files[target].path,
                    }
                    for origin, target in sorted(
                        edges,
                        key=lambda pair: (files[pair[0]].path, files[pair[1]].path),
                    )
                    if origin in member_ids and target in member_ids
                ],
                "instruction": "Navigation hints only: inspect port use, implementation and composition; verify dependency inversion, not folder labels.",
            }
        )
    # Prefer complete connected sets and distribute the bounded hints across projects.
    candidates.sort(key=lambda item: (-len(item["files"]), item["files"][0]["path"]))
    selected = []
    projects = set()
    for item in candidates:
        if item["project_id"] not in projects:
            projects.add(item["project_id"])
            selected.append(item)
    for item in candidates:
        if item not in selected:
            selected.append(item)
    return selected[:2], roles
