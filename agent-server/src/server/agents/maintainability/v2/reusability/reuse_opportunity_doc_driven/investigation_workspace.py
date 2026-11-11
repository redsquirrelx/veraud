"""Investigation-local discovery frontier; index hints are not semantic evidence."""

import json
import re
from copy import deepcopy

from .schemas import ReuseInvestigationTurn, ReuseToolQuery


def words(text):
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    return {part.casefold() for part in re.findall(r"[A-Za-z][A-Za-z0-9]+", text)
        if len(part) > 2} - {"shared", "common", "capability", "implementation", "service", "services"}


def missing_ranges(start, end, ranges):
    cursor = start
    for low, high in sorted(ranges):
        if high < cursor or low > end:
            continue
        if low > cursor:
            yield cursor, min(end, low - 1)
        cursor = max(cursor, high + 1)
    if cursor <= end:
        yield cursor, end


def _entity_rank(entity):
    roles = entity["roles"]
    return (3 if "provider" in roles else 2 if "consumer" in roles else 1,
        entity["relevance"], -len(entity["reasons"]))


def _prune_workspace(workspace, keep=12):
    """Keep the strongest provider/consumer/alternative leads, not every hint."""
    entities = workspace["entities"]
    alternatives = [(key, entity) for key, entity in entities.items()
        if entity["roles"] == ["alternative"]]
    if len(alternatives) <= keep:
        return
    retained = sorted(alternatives, key=lambda item: (_entity_rank(item[1]), item[0]), reverse=True)[:keep]
    selected = {key for key, _entity in retained}
    deferred = [(key, entity) for key, entity in alternatives if key not in selected]
    for key, entity in deferred:
        entities.pop(key)
        workspace["deferred_entities"].append({
            "path": entity["path"], "symbol_id": entity["symbol_id"], "relevance": entity["relevance"],
            "reason": "low-relevance discovery hint deferred; the tool may recover it on demand",
        })


class ReuseWorkspace:
    """Mixin using existing read-only tools, canonical query keys and source ledger."""

    def _indexes(self):
        if not hasattr(self, "_reuse_indexes"):
            snapshot = self.tools.accessible_snapshot
            self._reuse_indexes = ({item.id: item for item in snapshot.files},
                {item.path: item for item in snapshot.files}, {item.id: item for item in snapshot.symbols})
        return self._reuse_indexes

    def _workspace(self, state):
        task = self._current(state)
        saved = state.get("investigation_workspace", {})
        if saved.get("investigation_id") == task.id:
            return deepcopy(saved)
        workspace = {
            "investigation_id": task.id, "entities": {}, "comparisons": [], "claims_read": [],
            "attempts": {}, "exhausted_queries": [], "decisions": [], "gaps": [],
            "blocked": [], "rejected_paths": [], "progress": [], "focus_keys": [],
            "deferred_entities": [], "queries_executed": 0,
            "last_fingerprint": None, "discovery_initialized": False,
        }
        self._seed_entities(state, workspace)
        return workspace

    def _add_entity(self, workspace, path, role, reason, symbol_id=None, line=None, relevance=0):
        key = symbol_id or path
        entity = workspace["entities"].setdefault(key, {
            "path": path, "symbol_id": symbol_id, "roles": [], "reasons": [],
            "line": line, "relevance": relevance,
        })
        if role not in entity["roles"]:
            entity["roles"].append(role)
        if reason not in entity["reasons"]:
            entity["reasons"].append(reason)
        entity["relevance"] = max(entity["relevance"], relevance)
        _prune_workspace(workspace)

    def _seed_entities(self, state, workspace):
        task = self._current(state)
        snapshot = self.tools.accessible_snapshot
        files, _paths, _symbols = self._indexes()
        claims = self._document_claims(state, task)
        text = " ".join([task.capability, *task.providers, *task.consumers,
            *(item.get("subject", "") + " " + item.get("statement", "") for item in claims.values()),
            *(evidence.get("quote", "") for item in claims.values() for evidence in item.get("evidence", []))])
        tokens = words(" ".join([task.capability, *task.providers]))
        provider_labels = {value.strip().rstrip("/") for value in task.providers}
        consumer_labels = {value.strip().rstrip("/") for value in task.consumers}
        for symbol in snapshot.symbols:
            file = files.get(symbol.file_id)
            if file is None:
                continue
            labels = {symbol.id, symbol.name, symbol.qualified_name, file.path}
            explicit = any(re.search(r"(?<![\w])" + re.escape(label) + r"(?![\w])", text)
                for label in (symbol.name, symbol.qualified_name) if len(label) > 3)
            targeted = any(file.path == path.rstrip("/") or file.path.startswith(path.rstrip("/") + "/")
                for path in task.initial_targets)
            overlap = len(words(symbol.name) & tokens)
            role = "consumer" if labels & consumer_labels else "provider" if labels & provider_labels else (
                "provider" if explicit or file.path in task.initial_targets else "alternative")
            if explicit or labels & (provider_labels | consumer_labels) or (overlap and targeted):
                self._add_entity(workspace, file.path, role, "Documentary/symbol localization hint, not behavior proof.",
                    symbol.id, symbol.start_line, 10 * int(explicit) + overlap)
            elif overlap and len(words(symbol.name)) and overlap / len(words(symbol.name)) >= 0.5:
                self._add_entity(workspace, file.path, "alternative", "Name overlap is exploration only.",
                    symbol.id, symbol.start_line, overlap)
        known_paths = {entity["path"] for entity in workspace["entities"].values()}
        for file in snapshot.files:
            if file.path in known_paths:
                continue
            if file.path in task.initial_targets or file.path in provider_labels | consumer_labels:
                role = "consumer" if file.path in consumer_labels else "provider"
                self._add_entity(workspace, file.path, role, "Explicit file target; behavior location unresolved.")
        # Incoming edges discover possible consumers, not independent reimplementations.
        owners = {symbol.id: symbol.file_id for symbol in snapshot.symbols}
        providers = [entity for entity in workspace["entities"].values() if "provider" in entity["roles"]]
        provider_ids = {entity["symbol_id"] for entity in providers if entity["symbol_id"]}
        provider_files = {file.id for file in files.values() if any(file.path == entity["path"] for entity in providers)}
        for relation in snapshot.relationships:
            if relation.resolution != "internal" or relation.target_id not in provider_ids | provider_files:
                continue
            file = files.get(owners.get(relation.source_id, relation.source_id))
            if file:
                symbol = next((item for item in snapshot.symbols if item.id == relation.source_id), None)
                self._add_entity(workspace, file.path, "consumer", "Indexed incoming relationship; inspect behavior.",
                    symbol.id if symbol else None, symbol.start_line if symbol else None, 8)

    def _source_query(self, entity, state):
        _files, paths, symbols = self._indexes()
        file = paths.get(entity["path"])
        if not file or not file.line_count:
            return None
        symbol = symbols.get(entity["symbol_id"])
        if symbol is None and entity.get("line") is None and any(item.file_id == file.id for item in symbols.values()):
            return None  # Resolve the relevant function before reading a file's beginning.
        spans = self._symbol_spans(file.path, [symbol.name, symbol.qualified_name]) if symbol else []
        start, end = (symbol.start_line, symbol.end_line) if symbol else (
            spans[0] if spans else (entity.get("line") or 1, entity.get("line") or min(file.line_count, self.tools.limits.max_source_lines)))
        ranges = self._delivered_ranges(state).get(file.path, [])
        gap = next(missing_ranges(start, end, ranges), None)
        if gap is None:
            return None
        low, high = gap
        return ReuseToolQuery(tool="get_source_excerpt", arguments={"path": file.path,
            "start_line": low, "end_line": min(high, low + self.tools.limits.max_source_lines - 1)},
            reason="Inspect the relevant behavior and complete its unread range.",
            scope_expansion="Follow a documented entity, search match or indexed consumer relevant to the hypothesis.")

    def _next_queries(self, state, workspace, *, refresh=False):
        """Finite, deduplicated frontier; pagination and source tails need no LLM."""
        task = self._current(state)
        options = []
        # Bodies omitted from a compact prompt can be rehydrated without another
        # tool execution or charge. Never count an unseen body as semantic proof.
        for key in state["active_query_keys"] if refresh else []:
            view = state["query_cache"][key]
            if (view["tool_name"] == "get_source_excerpt" and view["status"] == "ok"
                    and any(item["id"] not in workspace.get("exposed_source_ids", []) for item in view.get("evidence", []))
                    and workspace.get("exposed_source_ids") is not None):
                tool, args = json.loads(key)
                options.append((-1, 0, ReuseToolQuery(tool=tool, arguments=args,
                    reason="Rehydrate an unread cached body omitted by the previous context allowance.",
                    scope_expansion="Recover previously inspected relevant source.")))
        candidates = [item for item in workspace["entities"].values() if item["roles"] != ["related"]]
        for entity in candidates:
            query = self._source_query(entity, state)
            if query:
                priority = 0 if "provider" in entity["roles"] else 1 if "consumer" in entity["roles"] else 2
                options.append((priority, -entity["relevance"], query))
            elif entity["symbol_id"] is None:
                options.append((2, -entity["relevance"], ReuseToolQuery(tool="find_symbols",
                    arguments={"file_path": entity["path"]}, reason="Locate relevant behavior inside the file before reading source.",
                    scope_expansion="Resolve an indexed consumer/provider hint relevant to the hypothesis.")))
        candidates = [item for item in workspace["entities"].values() if item["roles"] != ["related"]]
        for entity in candidates:
            if "provider" not in entity["roles"]:
                continue
            symbol = next((item for item in self.tools.accessible_snapshot.symbols if item.id == entity["symbol_id"]), None)
            file = next((item for item in self.tools.accessible_snapshot.files if item.path == entity["path"]), None)
            target = symbol.id if symbol else file.id if file else None
            if target:
                options.append((3, 0, ReuseToolQuery(tool="list_relationships", arguments={"target_id": target},
                    reason="Locate actual indexed callers/consumers of the provider.")))
            if symbol:
                options.append((4, 0, ReuseToolQuery(tool="search_repository_text", arguments={"query": symbol.name},
                    reason="Locate consumers and independent references beyond indexed relationships.")))
        if not workspace["entities"]:
            # Ask a focused literal search, not a directory's first ten files.
            for label in [*task.providers, *task.consumers, task.capability]:
                options.append((3, 0, ReuseToolQuery(tool="search_repository_text", arguments={"query": label[:1000]},
                    reason="Resolve the documented capability before choosing source files.")))
        # Continue incomplete pages and explicitly truncated source, regardless of chronological position.
        for key in state["active_query_keys"]:
            view = state["query_cache"][key]
            tool, args = json.loads(key)
            data = view.get("data", {})
            if view["status"] != "ok":
                continue
            next_offset = data.get("next_offset")
            if next_offset is not None and tool in {"list_files", "find_symbols", "list_relationships", "search_repository_text"}:
                options.append((5, 0, ReuseToolQuery(tool=tool, arguments={**args, "offset": next_offset},
                    reason="Continue a relevant discovery page; earlier pages are not exhaustive.")))
        selected, seen = [], set()
        for _priority, _score, query in sorted(options, key=lambda item: (item[0], item[1], json.dumps(item[2].arguments, sort_keys=True))):
            if query.tool not in self.config.tools:
                continue
            args, key = self._normalize_query(query, task)
            if key in seen or key in workspace["exhausted_queries"]:
                continue
            seen.add(key)
            if key in state["active_query_keys"] and _priority != -1:
                continue
            selected.append(query.model_copy(update={"arguments": args}))
            batch_limit = next(bound.max_length for bound in ReuseInvestigationTurn.model_fields["queries"].metadata
                if hasattr(bound, "max_length"))
            if len(selected) >= batch_limit:
                break
        return selected

    def _ingest_view(self, state, workspace, view):
        if view["status"] != "ok":
            return
        data, tool = view.get("data", {}), view["tool_name"]
        files, paths, symbols = self._indexes()
        for row in data.get("items", []):
            if tool == "list_relationships":
                source = symbols.get(row.get("source_id"))
                file = files.get(source.file_id if source else row.get("source_id"))
                if file:
                    providers = {entity["symbol_id"] for entity in workspace["entities"].values()
                        if "provider" in entity["roles"]}
                    providers |= {item.id for item in files.values() if any(item.path == entity["path"]
                        and "provider" in entity["roles"] for entity in workspace["entities"].values())}
                    role = "consumer" if row.get("target_id") in providers else "related"
                    self._add_entity(workspace, file.path, role, "Tool-delivered relationship navigation.",
                        source.id if source else None, source.start_line if source else None, 6)
            elif tool in {"search_repository_text", "find_symbols", "list_files"}:
                path = row.get("path") or row.get("file_path")
                file = files.get(row.get("file_id")) or paths.get(path)
                if file:
                    symbol = symbols.get(row.get("id")) if tool == "find_symbols" else None
                    if symbol is None and row.get("line"):
                        containing = [item for item in symbols.values() if item.file_id == file.id
                            and item.start_line <= row["line"] <= item.end_line]
                        symbol = min(containing, key=lambda item: item.end_line - item.start_line, default=None)
                    self._add_entity(workspace, file.path, "alternative", "Tool-delivered match; role requires semantic assessment.",
                        symbol.id if symbol else None, symbol.start_line if symbol else row.get("line"), 4)
