"""Evidence-driven investigate/tools controller. Planning is intentionally unchanged."""

import hashlib
import json
import math
import re
from uuid import uuid4

from pydantic import ValidationError

from server.agent_services.budgeting.policy import budgets_enabled
from server.runtimes.investigation.structured import safe_diagnostic
from server.runtimes.repository.access import (
    RepositoryAccessError,
    repository_relative_path,
)
from server.runtimes.repository.tools import TOOL_SCHEMAS, tool_signatures

from .investigation_evidence import ReuseEvidenceGate, invalid
from .investigation_workspace import ReuseWorkspace, _entity_rank
from .planning import complementary_claims
from .schemas import ReuseInvestigationResult, ReuseInvestigationTurn


def _compact_diagnostics(workspace):
    entities = workspace["entities"]
    by_role = {role: sum(role in item["roles"] for item in entities.values())
        for role in ("provider", "consumer", "alternative", "related")}
    comparison_outcomes = {}
    for comparison in workspace["comparisons"]:
        comparison_outcomes[comparison["outcome"]] = comparison_outcomes.get(comparison["outcome"], 0) + 1
    return {"queries_executed": workspace.get("queries_executed", 0),
        "gaps": workspace["gaps"], "blocked": workspace["blocked"],
        "evidence_entities": {"count": len(entities), "by_role": by_role,
            "retained": [{"path": item["path"], "symbol_id": item["symbol_id"],
                "roles": item["roles"], "relevance": item["relevance"]}
                for item in sorted(entities.values(), key=_entity_rank, reverse=True)[:6]],
            "deferred": len(workspace["deferred_entities"])},
        "comparisons": {"count": len(workspace["comparisons"]), "by_outcome": comparison_outcomes,
            "pending": sum(item["outcome"] == "insufficient" for item in workspace["comparisons"])},
        "rejected_paths": workspace["rejected_paths"][:6], "deferred_entities": workspace["deferred_entities"][-6:],
        "progress_steps": len(workspace["progress"]), "decisions": len(workspace["decisions"]),
        "remaining_budget": workspace.get("remaining_budget")}


class ReuseInvestigation(ReuseWorkspace, ReuseEvidenceGate):
    def route_investigation(self, state):
        if state["pending_queries"]:
            return "tools"
        return "investigate" if state["current_investigation"] < len(state["plan"].investigations) else "complete"

    def route_after_plan(self, state):
        return "investigate" if state.get("plan") and state["plan"].investigations else "end"

    def _current(self, state):
        return state["plan"].investigations[state["current_investigation"]]

    @staticmethod
    def _document_claims(state, task):
        return {key: state["plan"].document_claims[key] for key in task.document_claim_ids
            if key in state["plan"].document_claims}

    def _documentary_context(self, state):
        task = self._current(state)
        records = state["plan"].document_claims
        anchors = set(task.document_claim_ids) & records.keys()
        selected = complementary_claims(anchors, records) if anchors else []
        return {"document_claim_ids": task.document_claim_ids,
            "claims": {key: records[key] for key in selected}}

    @staticmethod
    def _normalized_identifier(value):
        return re.sub(r"[^a-z0-9]", "", (value or "").casefold())

    def _symbol_spans(self, path, names):
        file = next((item for item in self.tools.accessible_snapshot.files if item.path == path), None)
        return [(symbol.start_line, symbol.end_line) for symbol in self.tools.accessible_snapshot.symbols
            if file and symbol.file_id == file.id and {symbol.name, symbol.qualified_name, symbol.id} & set(names)]

    def _normalize_query(self, query, task):
        if query.tool not in self.config.tools:
            raise invalid("disabled_tool")
        try:
            args = TOOL_SCHEMAS[query.tool].model_validate(query.arguments).model_dump()
        except ValidationError:
            raise invalid("tool_arguments_invalid") from None
        for field in ("path", "file_path", "path_prefix"):
            if args.get(field) is not None:
                try:
                    args[field] = repository_relative_path(args[field], allow_root=field == "path_prefix")
                except RepositoryAccessError:
                    raise invalid("tool_arguments_invalid") from None
        if budgets_enabled() and "limit" in args:
            args["limit"] = min(args["limit"], self.tools.limits.max_page_size)
        target = args.get("path") or args.get("file_path")
        if target and task.initial_targets and not any(target == prefix.rstrip("/")
                or target.startswith(prefix.rstrip("/") + "/") for prefix in task.initial_targets) \
                and not query.scope_expansion.strip():
            raise invalid("scope_expansion_reason_required")
        if query.tool == "get_source_excerpt":
            file = next((item for item in self.tools.accessible_snapshot.files if item.path == args["path"]), None)
            if file is None or not file.line_count or args["start_line"] > file.line_count:
                raise invalid("tool_arguments_invalid")
            start = args["start_line"]
            args["end_line"] = min(args["end_line"] or file.line_count,
                start + self.tools.limits.max_source_lines - 1, file.line_count)
            if args["end_line"] < start:
                raise invalid("tool_arguments_invalid")
        return args, json.dumps([query.tool, args], sort_keys=True)

    def _delivered_ids(self, state):
        return {record["id"] for key in state["active_query_keys"]
            for record in state["query_cache"][key].get("evidence", [])}

    def _delivered_ranges(self, state):
        ranges = {}
        # Global cache entries are not delivered to a new investigation until
        # explicitly activated by the tools node.
        for key in state["active_query_keys"]:
            view = state["query_cache"][key]
            if view["status"] != "ok" or view["tool_name"] != "get_source_excerpt":
                continue
            data = view["data"]
            if data.get("start_line") is not None and data.get("end_line") is not None:
                ranges.setdefault(data["path"], []).append([data["start_line"], data["end_line"]])
        return ranges

    def _examined_relationships(self, state):
        snapshot = {item.id: item for item in self.tools.accessible_snapshot.relationships}
        examined = {}
        for key in state["active_query_keys"]:
            view = state["query_cache"][key]
            if view["status"] == "ok" and view["tool_name"] == "list_relationships":
                for row in view["data"].get("items", []):
                    item = snapshot.get(row.get("id"))
                    if item and (row.get("source_id"), row.get("target_id")) == (item.source_id, item.target_id):
                        examined[item.id] = item
        return examined

    def _remaining(self):
        if not budgets_enabled():
            limit = lambda value: None if math.isinf(value) else max(0, value)
            remaining = self.remaining_seconds()
            return {"model_calls": limit(self.call_limit - self.calls),
                "tool_calls": limit(self.tool_limit - self.tools.budget_usage.tool_calls),
                "accounted_tokens": self.tokens, "estimated_tokens": self.estimates,
                "tokens": None, "seconds": remaining, "budgets_enabled": False}
        finite = lambda number: None if math.isinf(number) else max(0, number)
        return {"model_calls": finite(self.call_limit - self.calls),
            "tool_calls": finite(self.tool_limit - self.tools.budget_usage.tool_calls),
            "accounted_tokens": self.tokens, "estimated_tokens": self.estimates,
            "tokens": max(0, min(self.token_limit - self.tokens,
                self.tools.token_budget.remaining if self.tools.token_budget else self.token_limit)) if budgets_enabled() else None,
            "seconds": finite(self.remaining_seconds()), "budgets_enabled": budgets_enabled()}

    def _blocker(self):
        self.timing.check_cancellation()
        if self.stop:
            return self.stop
        remaining = self._remaining()
        if remaining["model_calls"] == 0:
            return "model_call_limit"
        if remaining["seconds"] is not None and remaining["seconds"] == 0:
            return "time_limit"
        if remaining["tokens"] is not None and remaining["tokens"] <= 0:
            return "token_limit"
        return None

    def _tools_available(self):
        if self._blocker():
            return False
        if self.tools.budget_usage.tool_calls >= self.tool_limit:
            return False
        return not budgets_enabled() or self.tools.retrieval_budget.used < self.tools.retrieval_budget.limit

    def _investigation_context(self, state):
        task, workspace = self._current(state), state["investigation_workspace"]
        references = self._active_references(state)
        claims = self._documentary_context(state)
        compact_claims = {key: {field: value for field, value in record.items()
            if field in {"subject", "statement", "constraint", "certainty", "section_ids"}}
            for key, record in claims["claims"].items()}
        original_ids = set(workspace["claims_read"]) | {key for key, value in claims["claims"].items()
            if value.get("constraint") in {"exception", "allowed"}}
        originals = {key: claims["claims"][key] for key in original_ids if key in claims["claims"]}
        context = {
            "investigation": task.model_dump(mode="json"),
            "criteria": state["criteria"], "commit": state["commit"],
            "snapshot_hash": self.tools.context.input.snapshot_hash,
            "workspace": {key: workspace[key] for key in ("entities", "comparisons", "gaps", "blocked", "rejected_paths")},
            "documentary_context": {"document_claim_ids": task.document_claim_ids, "claims": compact_claims,
                "original_claims": originals, "recovery": "Use read_document_claim_ids to retrieve exact original quotes and provenance."},
            "remaining_budget": self._remaining(),
            "delivered_ranges": self._delivered_ranges(state),
            "tools": {key: value for key, value in tool_signatures().items() if key in self.config.tools},
            "evidence": [{"id": ref.id, "path": ref.path, "kind": ref.kind,
                "start_line": ref.start_line, "end_line": ref.end_line, "symbol_ids": ref.symbol_ids}
                for ref in references.values()],
            "visible_symbol_ids": sorted({symbol for ref in references.values() for symbol in ref.symbol_ids}),
            "symbols": [{"id": symbol.id, "name": symbol.name, "path": entity["path"],
                "start_line": symbol.start_line, "end_line": symbol.end_line}
                for key, entity in workspace["entities"].items() if (symbol := self._symbol_map().get(key))],
            "coverage_gap": workspace["gaps"], "tool_results": [],
            "reusable_queries": [json.loads(key) for key in state["active_query_keys"]],
            "limitations": state["task_limitations"],
        }
        # Prefer requested rehydration, unread behavior, then recent relevant
        # results. Omit whole result bodies, with an exact recovery query.
        keys = list(dict.fromkeys([*reversed(workspace["focus_keys"]), *reversed(state["active_query_keys"])]))
        limit = min(self.config.max_context_characters, 2 * self.tools.context.input.budget.max_input_tokens_per_call)
        context["workspace"]["entities"] = {
            key: {field: item[field] for field in ("path", "symbol_id", "roles", "line", "relevance")}
            for key, item in sorted(workspace["entities"].items(), key=lambda pair: _entity_rank(pair[1]), reverse=True)[:8]}
        context["workspace"]["priority_comparison"] = [{
            "symbol_id": item["symbol_id"], "path": item["path"], "roles": item["roles"],
            "relevance": item["relevance"], "reason": "Compare an inspected role against another before discovery.",
        } for item in sorted(workspace["entities"].values(), key=_entity_rank, reverse=True)
            if item["symbol_id"]][:4]
        context["workspace"]["comparisons"] = [{field: item[field] for field in (
            "shared_symbol_id", "other_symbol_id", "other_role", "outcome", "rationale",
            "shared_evidence_ids", "other_evidence_ids")} for item in workspace["comparisons"]]
        # Metadata has a compact operational view; raw originals remain in the
        # workspace/cache/plan. Prefer source catalogs to metadata-only receipts.
        context["evidence"].sort(key=lambda item: item["kind"] != "source")
        metadata_omissions = {}
        for name in ("reusable_queries", "symbols", "evidence"):
            while len(context[name]) > 1 and len(json.dumps(context, ensure_ascii=True)) > limit // 3:
                context[name].pop()
                metadata_omissions[name] = metadata_omissions.get(name, 0) + 1
        entity_view = context["workspace"]["entities"]
        while len(entity_view) > 1 and len(json.dumps(context, ensure_ascii=True)) > limit // 3:
            entity_view.pop(next(reversed(entity_view)))
            metadata_omissions["entities"] = metadata_omissions.get("entities", 0) + 1
        context["metadata_omissions"] = metadata_omissions
        context["query_inventory"] = [{"tool": state["query_cache"][key]["tool_name"],
            "status": state["query_cache"][key]["status"],
            "result_count": len(state["query_cache"][key].get("data", {}).get("items", [])),
            "query": json.loads(key)} for key in state["active_query_keys"][-self.tools.limits.max_metadata_items:]]
        omitted = []
        for key in keys:
            view = state["query_cache"][key]
            item = {field: view[field] for field in ("tool_name", "status", "data", "error") if field in view}
            item["recovery_query"] = json.loads(key)
            item["evidence_ids"] = [record["id"] for record in view.get("evidence", [])]
            context["tool_results"].append(item)
            # Keep space for stable prompt/schema/message escaping and repairs.
            if len(json.dumps(context, ensure_ascii=True)) > limit // 2:
                context["tool_results"].pop()
                omitted.append(json.loads(key))
            else:
                workspace.setdefault("exposed_source_ids", [])
                for record in view.get("evidence", []):
                    if record["id"] not in workspace["exposed_source_ids"]:
                        workspace["exposed_source_ids"].append(record["id"])
        # Recovery recipes may themselves be large. A count explicitly records
        # additional omissions; list_relationships/search/get_source remain usable.
        context["omitted_result_recovery_queries"] = omitted[:self.tools.limits.max_metadata_items]
        context["omitted_result_count"] = len(omitted)
        context["context_exhausted"] = bool(omitted and not context["tool_results"])
        return context

    def _remember_comparisons(self, turn, workspace):
        values = [*turn.comparisons, *(turn.conclusion.comparisons if turn.conclusion else [])]
        for item in values:
            record = item.model_dump(mode="json")
            # Replace an earlier insufficient comparison, never append duplicate
            # versions of the same pair to inflate progress.
            pair = (item.shared_symbol_id, item.other_symbol_id)
            workspace["comparisons"] = [previous for previous in workspace["comparisons"]
                if (previous["shared_symbol_id"], previous["other_symbol_id"]) != pair]
            workspace["comparisons"].append(record)
            symbols = self._symbol_map()
            files = {file.id: file.path for file in self.tools.accessible_snapshot.files}
            for identifier, role in [(item.shared_symbol_id, "provider"), (item.other_symbol_id,
                    "consumer" if item.other_role == "consumer" else "alternative")]:
                symbol = symbols[identifier]
                self._add_entity(workspace, files[symbol.file_id], role,
                    "Model-selected comparison target; evidence still required.", symbol.id, symbol.start_line, 20)
        if turn.conclusion:
            symbols = self._symbol_map()
            files = {file.id: file.path for file in self.tools.accessible_snapshot.files}
            for candidate in turn.conclusion.candidates:
                for identifier in candidate.shared_symbol_ids + candidate.independent_symbol_ids:
                    symbol = symbols[identifier]
                    role = "provider" if identifier in candidate.shared_symbol_ids else "alternative"
                    self._add_entity(workspace, files[symbol.file_id], role,
                        "Candidate target requiring inspected source.", symbol.id, symbol.start_line, 20)
        files, _paths, symbols = self._indexes()
        workspace["rejected_paths"] = [{"path": files[symbols[item["other_symbol_id"]].file_id].path,
            "symbol_id": item["other_symbol_id"], "reason": item["rationale"]}
            for item in workspace["comparisons"] if item["outcome"] in {"correct_reuse", "justified_independence"}]

    def _queue(self, state, workspace, queries):
        if any(self._normalize_query(query, self._current(state))[1] in state["active_query_keys"] for query in queries):
            workspace["interpret_next"] = True
        return {"pending_queries": queries, "investigation_workspace": workspace,
            "model_calls": self.calls, "initial_evidence_loaded": True}

    async def investigate(self, state):
        state = dict(state)
        workspace = self._workspace(state)
        state["investigation_workspace"] = workspace
        task = self._current(state)
        references = list(self._active_references(state).values())
        workspace["gaps"] = self._coverage_gap(state, task, references)
        blocker = self._blocker()
        if blocker:
            return self._inconclusive(state, workspace, blocker)
        if workspace.get("stalled_repeated"):
            return self._inconclusive(state, workspace, "no_progress")
        queries = self._next_queries(state, workspace) if self._tools_available() else []
        source_gaps = [gap for gap in workspace["gaps"] if gap != "functional_comparison_missing"]
        interpret_next = workspace.pop("interpret_next", False)
        if queries and not interpret_next and (not workspace["discovery_initialized"] or source_gaps):
            workspace["discovery_initialized"] = True
            return self._queue(state, workspace, queries)
        self._last_validation_failure = None
        issue_start = len(self.issues)
        turn = await self.call("investigate", state, ReuseInvestigationTurn)
        if turn is None:
            local_schema_failure = any("response_schema" in issue for issue in self.issues[issue_start:])
            failure = getattr(self, "_last_validation_failure", None)
            reason = "validation:" + failure["code"] if failure else self.stop or "invalid_investigation_response"
            if local_schema_failure and failure is None:
                reason = "validation:schema_recovery_exhausted"
                workspace["blocked"].extend(issue for issue in self.issues[issue_start:] if "response_schema" in issue)
            if (local_schema_failure and self.stop == "model_or_schema_error") or self.stop in {"input_token_limit", "context_limit"}:
                # Per-task schema failure is not a permanent provider outage.
                self.stop = ""
            return self._inconclusive(state, workspace, reason)
        self._remember_comparisons(turn, workspace)
        signature = hashlib.sha256(json.dumps({"turn": turn.model_dump(mode="json"),
            "progress": self._progress_signature(state, workspace)}, sort_keys=True).encode()).hexdigest()
        repeated = signature in workspace["decisions"]
        workspace["decisions"].append(signature)
        if turn.action == "tools":
            queries = []
            for query in turn.queries:
                _args, key = self._normalize_query(query, task)
                if key not in workspace["exhausted_queries"] and (not repeated):
                    queries.append(query)
            fresh_docs = set(turn.read_document_claim_ids) - set(workspace["claims_read"])
            workspace["claims_read"] = sorted(set(workspace["claims_read"]) | fresh_docs)
            if queries and self._tools_available():
                return self._queue(state, workspace, queries)
            if fresh_docs:
                return {"investigation_workspace": workspace, "model_calls": self.calls}
            auto = self._next_queries(state, workspace, refresh=True) if self._tools_available() else []
            if auto:
                return self._queue(state, workspace, auto)
            return self._inconclusive(state, workspace, "no_progress" if repeated else "no_useful_queries")
        conclusion = turn.conclusion
        # Pending workspace comparisons are preserved even if omitted from a
        # later concise close. They are rechecked against the cited ledger.
        from .schemas import ReuseFunctionalComparison
        conclusion = conclusion.model_copy(update={"comparisons": [
            ReuseFunctionalComparison.model_validate(item) for item in workspace["comparisons"]]})
        gaps = self._coverage_gap(state, task, list(self._active_references(state).values()), conclusion)
        workspace["gaps"] = gaps
        if gaps or conclusion.status == "inconclusive":
            auto = self._next_queries(state, workspace, refresh=True) if self._tools_available() else []
            if auto:
                workspace["blocked"].append("premature_close:" + ",".join(gaps))
                return self._queue(state, workspace, auto)
            # When both bodies are already present, the missing work may be
            # semantic interpretation, not another source read. Ask once per
            # evidence state, without consuming a structural schema retry.
            if gaps == ["functional_comparison_missing"]:
                evidence_state = hashlib.sha256(json.dumps(self._progress_signature(state, workspace),
                    sort_keys=True).encode()).hexdigest()
                requested = workspace.setdefault("interpretation_requests", [])
                if evidence_state not in requested:
                    requested.append(evidence_state)
                    workspace["interpret_next"] = True
                    return {"investigation_workspace": workspace, "model_calls": self.calls}
            if gaps and conclusion.status != "inconclusive":
                return self._inconclusive(state, workspace, "evidence_insufficient")
        if repeated:
            return self._inconclusive(state, workspace, "no_progress")
        return self._close_investigation(state, workspace, conclusion)

    @staticmethod
    def _progress_signature(state, workspace):
        source = {record["id"] for key in state["active_query_keys"]
            for record in state["query_cache"][key].get("evidence", []) if record.get("kind") == "source"}
        comparisons = [{"pair": [item["shared_symbol_id"], item["other_symbol_id"]],
            "resolved": item["outcome"] != "insufficient",
            "evidence": sorted(set(item["shared_evidence_ids"] + item["other_evidence_ids"]))}
            for item in workspace["comparisons"]]
        return {"source": sorted(source), "entities": sorted(workspace["entities"]),
            "comparisons": comparisons, "claims_read": workspace["claims_read"],
            "exposed": sorted(workspace.get("exposed_source_ids", []))}

    def _inconclusive(self, state, workspace, reason):
        references = list(self._active_references(state).values())
        source = [ref for ref in references if ref.kind == "source"]
        workspace["blocked"].append(reason)
        conclusion = ReuseInvestigationResult(investigation_id=self._current(state).id, status="inconclusive",
            summary="The inspected evidence does not yet support a reuse decision.",
            justification="Investigation stopped: " + reason,
            components=list(dict.fromkeys(ref.path for ref in source))[:40],
            evidence_ids=[ref.id for ref in references][:80],
            limitations=list(dict.fromkeys([reason, *workspace["gaps"], *state["task_limitations"]])))
        return self._close_investigation(state, workspace, conclusion)

    def _close_investigation(self, state, workspace, conclusion):
        # Verify every retrieved source in the ledger, including uncited reads.
        ledger, mismatch = self.verify_references(self.references())
        if mismatch and conclusion.status != "inconclusive":
            conclusion = conclusion.model_copy(update={"status": "inconclusive", "candidates": [],
                "limitations": [*conclusion.limitations, "source_provenance_unverified"]})
        if "remaining_budget" not in workspace:
            workspace["remaining_budget"] = self._remaining()
        conclusion = conclusion.model_copy(update={
            "inspected_scope": conclusion.inspected_scope or list(conclusion.components),
            "diagnostics": _compact_diagnostics(workspace),
        })
        results = [*state["investigation_results"], conclusion]
        status_map = {"reuse_opportunity": "confirmed", "no_reuse_opportunity": "discarded", "inconclusive": "inconclusive"}
        hypotheses = [hypothesis.model_copy(update={"status": status_map[conclusion.status],
            "evidence_ids": conclusion.evidence_ids, "rationale": conclusion.justification})
            if hypothesis.id == conclusion.investigation_id else hypothesis for hypothesis in state["hypotheses"]]
        done = state["current_investigation"] + 1 >= len(state["plan"].investigations)
        partial = bool(self.stop or any(item.status == "inconclusive" for item in results)
            or state["result"].planning_diagnostics.get("pending_groups")
            or state["result"].planning_diagnostics.get("omitted_claim_ids"))
        candidates = [candidate for item in results for candidate in item.candidates]
        diagnostics = {item.investigation_id: item.diagnostics for item in results}
        result = state["result"].model_copy(update={"investigation_results": results, "candidates": candidates,
            "hypotheses": hypotheses, "evidence": ledger,
            "status": "investigation_partial" if partial or not done else "investigation_complete",
            "termination_reason": self.stop or ("investigations_partial" if done and partial else
                "investigations_completed" if done else "investigating"),
            "limitations": list(dict.fromkeys([*state["limitations"], *conclusion.limitations,
                "Scoped investigation only; candidates have not undergone synthesis or critical review."])),
            "missing_information": [item.justification for item in results if item.status == "inconclusive"],
            "model_calls": self.calls, "tool_calls": self.tools.budget_usage.tool_calls,
            "accounted_tokens": self.tokens, "estimated_tokens": self.estimates,
            "deferred_stages": self.deferred_stages, "iterations": state["iterations"] + 1,
            "investigation_diagnostics": diagnostics})
        return {"current_investigation": state["current_investigation"] + 1,
            "investigation_results": results, "candidates": candidates, "hypotheses": hypotheses,
            "pending_queries": [], "active_query_keys": [], "task_limitations": [],
            "initial_evidence_loaded": False, "investigation_workspace": {},
            "result": result, "evidence": ledger, "limitations": result.limitations,
            "model_calls": self.calls, "tool_calls": result.tool_calls,
            "iterations": result.iterations, "termination_reason": result.termination_reason}

    async def execute_investigation_tools(self, state):
        state = dict(state)
        workspace = self._workspace(state)
        cache, keys = dict(state["query_cache"]), list(state["active_query_keys"])
        limitations, focus = list(state["task_limitations"]), []
        remaining_tools_before = self.tools.budget_usage.tool_calls
        before = self._progress_signature(state, workspace)
        for query in state["pending_queries"]:
            self.timing.check_cancellation()
            args, key = self._normalize_query(query, self._current(state))
            if key in workspace["exhausted_queries"]:
                continue
            cached = cache.get(key)
            if cached and cached["status"] == "ok":
                view = cached
            else:
                if not self._tools_available():
                    workspace["blocked"].append(self._blocker() or "tool_or_retrieval_budget_exhausted")
                    break
                call_id = "reuse-investigate-" + uuid4().hex
                try:
                    response = self.tools.execute(query.tool, args, tool_call_id=call_id)
                    view = self.tools.model_view(response) | {"snapshot_hash": response.snapshot_hash}
                except Exception as error:  # noqa: BLE001 - tool boundary; cancellation propagates
                    view = {"tool_name": query.tool, "status": "error", "evidence": [],
                        "error": {"code": "tool_execution_error", "message": safe_diagnostic(error)}}
                workspace["attempts"][key] = workspace["attempts"].get(key, 0) + 1
                if view["status"] != "ok":
                    limitations.append("Tool query failed: " + view["error"]["code"])
                    # Existing configured retry policy, not unbounded new attempts.
                    if workspace["attempts"][key] > getattr(self.config, "max_tool_query_retries", 1):
                        workspace["exhausted_queries"].append(key)
                    continue
                cache[key] = view
            if key not in keys:
                keys.append(key)
            focus.append(key)
            self._ingest_view(state, workspace, view)
        state.update(query_cache=cache, active_query_keys=keys)
        workspace["focus_keys"] = focus
        workspace["queries_executed"] += self.tools.budget_usage.tool_calls - remaining_tools_before
        workspace["remaining_budget"] = self._remaining()
        after = self._progress_signature(state, workspace)
        fingerprint = hashlib.sha256(json.dumps(after, sort_keys=True).encode()).hexdigest()
        if before == after:
            workspace["stalled_repeated"] = workspace.get("stalled_signature") == fingerprint
            workspace["stalled_signature"] = fingerprint
        else:
            workspace["stalled_repeated"] = False
            workspace["stalled_signature"] = None
        workspace["progress"].append({"new_information": before != after,
            "active_queries": len(keys), "entities": len(workspace["entities"]),
            "comparisons": len(workspace["comparisons"])})
        return {"query_cache": cache, "active_query_keys": keys, "pending_queries": [],
            "task_limitations": list(dict.fromkeys(limitations)), "investigation_workspace": workspace,
            "tool_calls": self.tools.budget_usage.tool_calls, "evidence": self.references()}
