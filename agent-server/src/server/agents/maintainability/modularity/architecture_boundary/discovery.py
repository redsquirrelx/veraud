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

    def coverage(self, references, measurements=()):
        methods = {item.call_id: item.tool for item in measurements}
        sources = [item for item in references if item.kind == "source"]
        hits = {item.file_id for item in sources if methods.get(item.tool_call_id) == "search_repository_text"}
        excerpts = [item for item in sources if methods.get(item.tool_call_id) == "get_source_excerpt"
            or (item.tool_call_id not in methods and item.end_line > item.start_line)]
        inspected = {item.file_id for item in excerpts}
        ranges = defaultdict(list)
        for ref in excerpts:
            ranges[ref.file_id].append((ref.start_line, ref.end_line))
        lines = {}
        for file_id, spans in ranges.items():
            cursor, total = 0, 0
            for start, end in sorted(spans):
                total += max(0, end - max(cursor, start - 1))
                cursor = max(cursor, end)
            lines[file_id] = total
        complete = {file_id for file_id, count in lines.items()
            if self.files[file_id].line_count and count >= self.files[file_id].line_count}
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
            "search_hit_file_count": len(hits), "excerpt_file_count": len(inspected),
            "fully_inspected_file_count": len(complete), "source_lines_delivered": sum(lines.values()),
            "dependency_endpoint_pair_count": len({(source, target) for source, target, _ in self.edges
                if source in inspected and target in inspected}),
            "boundary_count": len(boundaries), "boundaries": boundaries,
            "unresolved_dependency_paths": sorted(self.files[item].path for item in self.uncertain),
            "limitations": ["Indexed boundaries are navigation, not runtime or exhaustive architecture coverage.",
                "Endpoint inspection does not establish that every relevant line was inspected.",
                "Search-hit lines are not counted as source-excerpt inspection; full-file coverage is measured separately."]}

    def ranked_files(self, texts, paths=()):
        text = " ".join(texts).lower()
        words = set(re.findall(r"[a-z_][a-z_0-9]{2,}", text)) - {
            "the", "and", "source", "inspect", "implementation", "evidence", "does", "with", "from"}
        seeds = {item.id for item in self.files.values()
                 if any(item.path == path or item.path.startswith(path + "/") for path in paths)}
        for item in self.files.values():
            if item.path.lower() in text:
                seeds.add(item.id)
        # Continue from concrete files through resolved dependencies, instead of
        # repeatedly selecting lexically similar headers elsewhere in the tree.
        neighbours = {other for seed in seeds for other in self.outgoing[seed] | self.incoming[seed]}
        entrypoints = {item.file_id for item in self.snapshot.entrypoints}

        def score(source):
            path_words = set(re.findall(r"[a-z_][a-z_0-9]{2,}", source.path.lower()))
            value = 20 * (source.id in seeds) + 12 * (source.id in neighbours) + 3 * len(words & path_words)
            value += 4 * (source.id in entrypoints)
            value += 3 * bool(re.search(r"config|container|bootstrap|wiring|adapter|client|database", source.path, re.IGNORECASE))
            value += min(5, len(self.incoming[source.id]) + len(self.outgoing[source.id]))
            if not seeds and re.search(r"(?:^|/)(?:tests?|\.github|\.vscode)(?:/|$)|(?:^|/)\.[^/]+$", source.path):
                value -= 12
            return -value, source.path

        return sorted(self.files.values(), key=score)

    def claim_issues(self, check, supported_paths, references):
        ids = {item.id for item in self.files.values() if item.path in check.scope_paths}
        issues = []
        if check.claim_kind in {"isolation", "deployment"}:
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

    def dependency_reads(self, seeds, references, max_lines, limit=6):
        """Navigation to imports and their targets; all bytes still require tools."""
        cited = {item.id for item in self.files.values() if item.path in seeds}
        refs = list(references)
        suggestions = []
        evidence = {item.id: item for item in self.snapshot.evidence}
        for source, target, relation in sorted(self.edges,
                key=lambda edge: (-bool(re.search(r"service|client|proxy|prisma|database|route", self.files[edge[1]].path)),
                    self.files[edge[0]].path, self.files[edge[1]].path, edge[2].id)):
            if source not in cited:
                continue
            for file_id in (source, target):
                location = next((evidence[i] for i in relation.evidence_ids
                    if i in evidence and evidence[i].file_id == file_id), None)
                start = location.start_line if location and location.start_line else 1
                end = (location.end_line or start) if location else min(self.files[file_id].line_count or 1, max_lines)
                if file_id == target:
                    functions = [item for item in self.snapshot.symbols
                        if item.file_id == target and item.kind in {"function", "method"}]
                    symbol = next((item for item in functions if item.id == relation.target_id), None)
                    symbol = symbol or next(iter(sorted(functions, key=lambda item: item.start_line)), None)
                    if symbol is not None:
                        start, end = symbol.start_line, symbol.end_line
                end = min(end, start + max_lines - 1)
                if any(ref.kind == "source" and ref.file_id == file_id and ref.start_line <= start
                        and ref.end_line >= end for ref in refs):
                    continue
                suggestion = {"tool": "get_source_excerpt", "arguments": {
                    "path": self.files[file_id].path, "start_line": start, "end_line": end},
                    "navigation_only": True, "reason": "inspect_dependency_endpoint",
                    "dependency_paths": [self.files[source].path, self.files[target].path]}
                if suggestion not in suggestions:
                    suggestions.append(suggestion)
                if len(suggestions) >= limit:
                    return suggestions
        return suggestions
