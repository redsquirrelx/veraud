"""Bounded deterministic navigation over existing indexes, never proof of quality."""

from collections import Counter

from ...repository_runtime.access import repository_relative_path
from .schemas import AbstractionCandidateTarget


def discover(snapshot, request, limit):
    targets = [repository_relative_path(t) for t in request.targets]
    files = {f.id: f for f in snapshot.files}

    def in_scope(path):
        return not targets or any(path == t or path.startswith(t.rstrip("/") + "/") for t in targets)

    for target in targets:
        if not any(f.path == target or f.path.startswith(target.rstrip("/") + "/") for f in files.values()):
            raise ValueError(f"Target is not accessible in the snapshot: {target}")
    incoming = Counter(r.target_id for r in snapshot.relationships if r.kind != "contains" and r.target_id)
    kinds = {"class", "interface", "abstract_class", "trait", "protocol", "function", "type_alias", "type"}
    symbols = [s for s in snapshot.symbols if s.file_id in files and in_scope(files[s.file_id].path)
               and s.kind.casefold() in kinds and s.parent_symbol_id is None]
    symbols.sort(key=lambda s: (-(incoming[s.id] + incoming[s.file_id]), -bool(s.base_names),
                               files[s.file_id].path, s.start_line, s.id))
    represented = {s.file_id for s in symbols}
    records = [(s.id, s.file_id, s.qualified_name, s.kind, s.start_line, s.end_line) for s in symbols]
    # Unsupported/missing language indexes remain inspectable; no new parser/service.
    records.extend((f.id, f.id, None, "file", None, None) for f in sorted(files.values(), key=lambda f: f.path)
                   if f.id not in represented and in_scope(f.path))
    selected = []
    for identifier, file_id, name, kind, start, end in records[:limit]:
        selected.append(AbstractionCandidateTarget(component_id=identifier, path=files[file_id].path,
            symbol_name=name, kind=kind, start_line=start, end_line=end,
            relationship_ids=[r.id for r in snapshot.relationships if r.kind != "contains"
                and (r.source_id in {identifier, file_id} or r.target_id in {identifier, file_id})][:16]))
    return selected, len(records)
