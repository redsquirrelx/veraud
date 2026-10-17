"""Snapshot-derived investigation navigation. Nothing here is delivered evidence."""

import re
from collections import defaultdict
from pathlib import PurePosixPath


class BoundaryDiscovery:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.files = {item.id: item for item in snapshot.files}
        self.owners = {item.id: item.file_id for item in snapshot.symbols}
        self.edges = []
        self.outgoing = defaultdict(set)
        self.incoming = defaultdict(set)
        self.uncertain = set()
        for relation in snapshot.relationships:
            source = self.owners.get(relation.source_id, relation.source_id)
            target = self.owners.get(relation.target_id, relation.target_id)
            if source not in self.files:
                continue
            if relation.resolution in {"dynamic", "unresolved"}:
                self.uncertain.add(source)
            if relation.resolution != "internal" or target not in self.files or source == target:
                continue
            self.edges.append((source, target, relation))
            self.outgoing[source].add(target)
            self.incoming[target].add(source)

    def component(self, file_id):
        source = self.files[file_id]
        parts = PurePosixPath(source.path).parts
        return source.project_id, parts[0] if len(parts) > 1 else "."

    def coverage(self, references):
        inspected = {item.file_id for item in references if item.kind == "source"}
        groups = defaultdict(list)
        for source, target, relation in self.edges:
            if self.component(source) != self.component(target):
                groups[(self.component(source), self.component(target))].append((source, target, relation))
        boundaries = []
        for key, edges in groups.items():
            paths = sorted({self.files[item].path for source, target, _ in edges for item in (source, target)})
            pending = sorted({self.files[item].path for source, target, _ in edges
                              for item in (source, target) if item not in inspected})
            boundaries.append({"components": [list(item) for item in key], "relationship_count": len(edges),
                "endpoint_paths": paths, "uninspected_paths": pending,
                "status": "endpoints_inspected" if not pending else "pending"})
        boundaries.sort(key=lambda item: (-bool(item["uninspected_paths"]), -item["relationship_count"],
                                          item["endpoint_paths"]))
        return {"navigation_only": True, "file_count": len(self.files), "inspected_file_count": len(inspected),
            "boundary_count": len(boundaries), "boundaries": boundaries,
            "unresolved_dependency_paths": sorted(self.files[item].path for item in self.uncertain),
            "limitations": ["Indexed boundaries are navigation, not runtime or exhaustive architecture coverage.",
                "Endpoint inspection does not establish that every relevant line was inspected."]}

    def ranked_files(self, texts, paths=()):
        text = " ".join(texts).lower()
        words = set(re.findall(r"[a-z_][a-z_0-9]{2,}", text)) - {
            "the", "and", "source", "inspect", "implementation", "evidence", "does", "with", "from"}
        seeds = {item.id for item in self.files.values()
                 if any(item.path == path or item.path.startswith(path + "/") for path in paths)}
        for item in self.files.values():
            if item.path.lower() in text:
                seeds.add(item.id)
        neighbours = {other for seed in seeds for other in self.outgoing[seed] | self.incoming[seed]}
        entrypoints = {item.file_id for item in self.snapshot.entrypoints}

        def score(source):
            path_words = set(re.findall(r"[a-z_][a-z_0-9]{2,}", source.path.lower()))
            value = 20 * (source.id in seeds) + 12 * (source.id in neighbours) + 3 * len(words & path_words)
            value += 4 * (source.id in entrypoints)
            value += 3 * bool(re.search(r"config|container|bootstrap|wiring|adapter|client|database", source.path, re.IGNORECASE))
            value += min(5, len(self.incoming[source.id]) + len(self.outgoing[source.id]))
            return -value, source.path

        return sorted(self.files.values(), key=score)

    def claim_issues(self, check, supported_paths, references):
        ids = {item.id for item in self.files.values() if item.path in check.scope_paths}
        issues = []
        if check.claim_kind == "isolation":
            neighbours = {other for item in ids for other in self.outgoing[item] | self.incoming[item]}
            if any(self.files[item].path not in supported_paths for item in neighbours):
                issues.append("boundary_related_endpoints_not_supported")
        if check.claim_kind == "absence_of_cycles":
            # Kahn's algorithm checks the induced file graph without recursion-depth limits.
            indegree = {item: len(self.incoming[item] & ids) for item in ids}
            ready = [item for item, degree in indegree.items() if degree == 0]
            visited = 0
            while ready:
                item = ready.pop()
                visited += 1
                for other in self.outgoing[item] & ids:
                    indegree[other] -= 1
                    if indegree[other] == 0:
                        ready.append(other)
            if visited != len(ids):
                issues.append("boundary_indexed_cycle_observed")
            cited = {item.evidence_id for item in check.support}
            refs = [item for item in references if item.id in cited and item.kind == "source"]
            by_id = {item.id: item for item in self.snapshot.evidence}
            for source, target, relation in self.edges:
                if source not in ids or target not in ids:
                    continue
                locations = [by_id[item] for item in relation.evidence_ids if item in by_id]
                if not locations or not any(ref.file_id == source and location.start_line is not None
                        and ref.start_line <= location.start_line and ref.end_line >= (location.end_line or location.start_line)
                        for location in locations for ref in refs):
                    issues.append("boundary_dependency_edges_not_inspected")
                    break
        if ids & self.uncertain:
            issues.append("boundary_unresolved_dependencies_in_scope")
        return issues
