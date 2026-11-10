"""Iterative responsibility investigation (investigate/tools loop).

Separated from execution.py so plan selection stays independent. The graph
shape is unchanged: investigate <-> tools until each investigation closes.
Source-less metadata never closes an investigation; source is required.
"""

import json
from uuid import uuid4

from pydantic_core import PydanticCustomError

from server.runtimes.investigation.structured import safe_diagnostic
from server.runtimes.repository.tools import TOOL_SCHEMAS, tool_signatures

from .schemas import (
    ResponsibilityInvestigationResult,
    ResponsibilityInvestigationTurn,
    ResponsibilityToolQuery,
)


def _invalid(code):
    feedback = ResponsibilityInvestigationTurn.validation_feedback.get(code, code)
    return PydanticCustomError(code, feedback)


class ResponsibilityInvestigation:
    def route_investigation(self, state):
        if state["pending_queries"]:
            return "tools"
        return "investigate" if state["current_investigation"] < len(state["plan"].candidates) else "synthesis"

    def _current(self, state):
        return state["plan"].candidates[state["current_investigation"]]

    def _file_id(self, path):
        for file in self.tools.accessible_snapshot.files:
            if file.path == path:
                return file.id
        return None

    def _initial_queries(self, candidate):
        file_id = self._file_id(candidate.primary_component)
        queries = [ResponsibilityToolQuery(tool="get_source_excerpt",
            arguments={"path": candidate.primary_component, "start_line": 1, "end_line": 40},
            reason="Inspect the primary component declarations and implementations.")]
        if file_id:
            queries.append(ResponsibilityToolQuery(tool="list_relationships",
                arguments={"source_id": file_id, "limit": 10},
                reason="Examine collaborator relationships of the primary component."))
            queries.append(ResponsibilityToolQuery(tool="find_symbols",
                arguments={"file_path": candidate.primary_component, "limit": 10},
                reason="Locate declarations inside the primary component."))
        return [query for query in queries if query.tool in self.config.tools]

    def _normalize_query(self, query, candidate):
        if query.tool not in self.config.tools:
            raise _invalid("disabled_tool")
        args = TOOL_SCHEMAS[query.tool].model_validate(query.arguments).model_dump()
        allowed = {candidate.primary_component, *candidate.collaborators}
        if query.tool == "get_source_excerpt" and args["path"] not in allowed and not query.scope_expansion.strip():
            raise _invalid("scope_expansion_reason_required")
        if query.tool == "find_symbols" and args.get("file_path") and args["file_path"] not in allowed and not query.scope_expansion.strip():
            raise _invalid("scope_expansion_reason_required")
        if query.tool == "get_source_excerpt":
            start = args["start_line"]
            args["end_line"] = min(args["end_line"] or start + 59, start + 59)
            for file in self.tools.accessible_snapshot.files:
                if file.path == args["path"] and file.line_count:
                    args["end_line"] = min(args["end_line"], file.line_count)
                    break
        return args, json.dumps([query.tool, args], sort_keys=True)

    def _delivered_ids(self, state):
        return {record["id"] for key in state["active_query_keys"]
            for record in state["query_cache"][key].get("evidence", [])}

    def _examined_relationships(self, state):
        indexed = {item.id: item for item in self.tools.accessible_snapshot.relationships}
        result = {}
        for key in state["active_query_keys"]:
            view = state["query_cache"][key]
            if view["tool_name"] != "list_relationships" or view["status"] != "ok":
                continue
            for row in view.get("data", {}).get("items", []):
                item = indexed.get(row.get("id"))
                if item and (row.get("source_id"), row.get("target_id")) == (item.source_id, item.target_id):
                    result[item.id] = item
        return result

    def _documentary_context(self, state):
        task = self._current(state)
        plan = state["plan"]
        claims = {}
        for key in task.document_claim_ids:
            record = getattr(plan, "document_claims", {}).get(key) if plan else None
            if record is None:
                continue
            dump = record.model_dump(mode="json")
            claims[key] = {"subject": dump["claim"]["subject"], "statement": dump["claim"]["statement"],
                "constraint": dump["claim"]["constraint"], "certainty": dump["claim"]["certainty"],
                "category": dump["claim"]["category"], "section_paths": dump["section_paths"],
                "status": dump["status"], "reason": dump["reason"], "scope_paths": dump["scope_paths"]}
        return {"document_claim_ids": list(task.document_claim_ids),
            "documented_responsibility": task.documented_responsibility,
            "claims": claims}

    def _investigation_context(self, state):
        task = self._current(state)
        snapshot = self.tools.accessible_snapshot
        owners = {item.id: item.file_id for item in snapshot.symbols}
        paths = {item.id: item.path for item in snapshot.files}
        results_all = []
        inventory = []
        for key in state["active_query_keys"]:
            view = state["query_cache"][key]
            tool = view["tool_name"]
            data = view.get("data", {})
            if tool == "get_source_excerpt" and isinstance(data, dict):
                data = {field: data[field] for field in ("path", "start_line", "end_line", "content", "truncated",
                    "requested_end_line") if field in data}
            elif tool == "list_relationships" and isinstance(data, dict):
                rows = []
                for row in data.get("items", []):
                    if row.get("id") not in self._examined_relationships(state):
                        continue
                    rows.append({"id": row.get("id"), "kind": row.get("kind"),
                        "source_path": paths.get(owners.get(row.get("source_id"), row.get("source_id"))),
                        "target_path": paths.get(owners.get(row.get("target_id"), row.get("target_id")))})
                data = {"items": rows,
                    "total": data.get("total"), "next_offset": data.get("next_offset")}
            results_all.append({"tool_name": tool, "status": view["status"],
                **({"data": data} if view["status"] == "ok" else {"error": view["error"]})})
            try:
                args = json.loads(key)
            except (TypeError, ValueError):
                args = []
            inventory.append({"tool_name": tool, "arguments": args[1] if len(args) > 1 else {},
                "status": view["status"],
                "evidence_ids": [record["id"] for record in view.get("evidence", [])]})
        recent = results_all[-3:] if results_all else []
        reusable = [json.loads(key) for key in state["active_query_keys"][:-3]] if results_all else []
        references = [record for record in self.references() if record.id in self._delivered_ids(state)]
        return {"investigation": {"id": task.id, "primary_component": task.primary_component,
                "collaborators": task.collaborators, "question": task.question,
                "documented_responsibility": task.documented_responsibility,
                "evidence_needed": task.evidence_needed, "document_claim_ids": task.document_claim_ids},
            "criteria": state["criteria"], "commit": state["commit"],
            "snapshot_hash": self.tools.context.input.snapshot_hash,
            "tools": {key: value for key, value in tool_signatures().items() if key in self.config.tools},
            "tool_results": recent,
            "query_inventory": inventory,
            "reusable_queries": reusable,
            "evidence": [{"id": record.id, "path": record.path, "kind": record.kind,
                "start_line": record.start_line, "end_line": record.end_line,
                "symbol_ids": record.symbol_ids} for record in references],
            "visible_symbol_ids": sorted({symbol for record in references for symbol in record.symbol_ids}),
            "coverage_gap": self._coverage_gap(state, task, references),
            "documentary_context": self._documentary_context(state),
            "limitations": state["task_limitations"]}

    def _coverage_gap(self, state, task, references):
        snapshot = self.tools.accessible_snapshot
        source = [record for record in references if record.kind == "source"]
        if not source:
            return ["No source evidence delivered for the primary component."]
        gaps = []
        file_ids = {item.id: item for item in snapshot.files}
        target = next((item for item in file_ids.values() if item.path == task.primary_component), None)
        if target and target.line_count:
            covered_end = max((record.end_line or 0) for record in source if record.file_id == target.id)
            if covered_end < target.line_count:
                gaps.append(f"Uninspected tail of {task.primary_component}: lines {covered_end + 1}-{target.line_count}.")
        unseen = [symbol for symbol in snapshot.symbols
            if symbol.file_id == (target.id if target else None)
            and not any(record.file_id == symbol.file_id and record.start_line is not None
                and record.start_line <= symbol.end_line
                and record.end_line is not None and record.end_line >= symbol.start_line
                for record in source)]
        if unseen:
            names = ", ".join(sorted({symbol.name for symbol in unseen})[:5])
            gaps.append(f"{len(unseen)} indexed declarations in {task.primary_component} not overlapping delivered source ({names}).")
        if not self._examined_relationships(state):
            gaps.append("No indexed relationships of the primary component examined.")
        return gaps

    def _validate_turn(self, turn, state):
        task = self._current(state)
        if turn.action == "tools":
            if not turn.queries or turn.conclusion is not None:
                raise _invalid("tools_requires_queries_without_conclusion")
            for query in turn.queries:
                self._normalize_query(query, task)
            return
        result = turn.conclusion
        if turn.queries or result is None or result.investigation_id != task.id:
            raise _invalid("close_requires_current_investigation_conclusion")
        if (result.status == "finding_candidate") != bool(result.candidates):
            raise _invalid("candidate_status_mismatch")
        if result.status == "inconclusive" and not result.limitations:
            raise _invalid("inconclusive_requires_limitations")
        if result.status == "no_finding" and task.primary_component not in result.components:
            raise _invalid("conclusion_requires_inspected_primary_component")
        references = {record.id: record for record in self.references() if record.id in self._delivered_ids(state)}
        if result.status != "inconclusive" and self._coverage_gap(state, task, list(references.values())):
            raise _invalid("coverage_incomplete")
        if set(result.evidence_ids) - references.keys():
            raise _invalid("unknown_or_undelivered_evidence")
        snapshot = self.tools.accessible_snapshot
        symbols = {symbol.id: symbol for symbol in snapshot.symbols}
        examined = set(self._examined_relationships(state))
        for subject in [result, *result.candidates]:
            if set(subject.relationship_ids) - examined:
                raise _invalid("unexamined_relationship")
            if set(subject.evidence_ids) - set(result.evidence_ids):
                raise _invalid("candidate_evidence_not_in_conclusion")
            cited = [references[key] for key in subject.evidence_ids if key in references]
            if result.status != "inconclusive":
                if not any(record.kind == "source" for record in cited) or not subject.components:
                    raise _invalid("conclusion_requires_inspected_source_and_components")
                _evidence, issues = self.evidence_issues(subject.evidence_ids, references)
                if issues:
                    raise _invalid("unverified_source_provenance")
            inspected = {record.path for record in cited if record.kind == "source"}
            if result.status != "inconclusive" and set(subject.components) - inspected:
                raise _invalid("uninspected_component")
            for identifier in subject.symbol_ids:
                symbol = symbols.get(identifier)
                if symbol is None or not any(record.kind == "source" and record.file_id == symbol.file_id
                        and record.start_line is not None and record.start_line <= symbol.end_line
                        and record.end_line is not None and record.end_line >= symbol.start_line for record in cited):
                    raise _invalid("uninspected_symbol")
        self._validate_claims(result, task, references)

    def _validate_claims(self, result, task, references):
        seen = set()
        for assessment in result.claim_assessments:
            key = assessment.claim_id
            if key not in task.document_claim_ids or key in seen:
                raise _invalid("invalid_document_claim_assessment")
            seen.add(key)
            if result.status == "no_finding" and assessment.status == "contradicted":
                raise _invalid("no_finding_with_contradiction")
            if set(assessment.code_evidence_ids) - references.keys():
                raise _invalid("unknown_or_undelivered_evidence")
            if set(assessment.code_evidence_ids) - set(result.evidence_ids):
                raise _invalid("claim_evidence_not_in_conclusion")
            cited = [references[identifier] for identifier in assessment.code_evidence_ids if identifier in references]
            if assessment.status in {"supported", "contradicted"}:
                if not any(record.kind == "source" for record in cited) or not assessment.scope_paths:
                    raise _invalid("claim_assessment_requires_source")
                if set(assessment.scope_paths) - {record.path for record in cited if record.kind == "source"}:
                    raise _invalid("claim_assessment_requires_uninspected_source")
        for candidate in result.candidates:
            if any(key not in seen for key in candidate.document_claim_ids):
                raise _invalid("candidate_document_claim_unassessed")
            if candidate.document_claim_ids and not candidate.independent_change_reasons:
                raise _invalid("candidate_document_claim_mismatch")
        if result.status == "finding_candidate":
            for candidate in result.candidates:
                if len({value.strip() for value in candidate.observed_responsibilities}) < 2:
                    raise _invalid("finding_requires_distinct_responsibilities")
        if result.status == "no_finding" and task.document_claim_ids and seen != set(task.document_claim_ids):
            raise _invalid("documentary_no_finding_requires_resolution")

    def _close_investigation(self, state, conclusion):
        results = [*state["investigation_results"], conclusion]
        status_map = {"finding_candidate": "confirmed", "no_finding": "discarded", "inconclusive": "inconclusive"}
        hypotheses = []
        for hypothesis in state["hypotheses"]:
            if hypothesis.id == conclusion.investigation_id:
                hypotheses.append(hypothesis.model_copy(update={
                    "status": status_map.get(conclusion.status, "inconclusive"),
                    "evidence_ids": list(conclusion.evidence_ids),
                    "rationale": conclusion.justification or conclusion.summary}))
            else:
                hypotheses.append(hypothesis)
        index = state["current_investigation"] + 1
        done = index >= len(state["plan"].candidates)
        ledger, _mismatch = self.verify_references(self.references())
        reason = self.stop or ("investigations_completed" if done else "investigating")
        limitations = list(dict.fromkeys([*state["limitations"], *conclusion.limitations, *self.issues]))
        result = state["result"].model_copy(update={"investigation_results": results,
            "hypotheses": hypotheses, "termination_reason": reason, "limitations": limitations,
            "evidence": ledger, "model_calls": self.calls, "tool_calls": self.tools.budget_usage.tool_calls,
            "accounted_tokens": self.tokens, "estimated_tokens": self.estimates,
            "deferred_stages": self.deferred_stages, "iterations": state["iterations"] + 1})
        return {"current_investigation": index, "investigation_results": results,
            "hypotheses": hypotheses,
            "pending_queries": [], "active_query_keys": [], "task_limitations": [],
            "initial_evidence_loaded": False, "result": result, "evidence": ledger,
            "limitations": limitations, "model_calls": self.calls,
            "tool_calls": self.tools.budget_usage.tool_calls,
            "iterations": state["iterations"] + 1, "termination_reason": reason}

    async def investigate(self, state):
        tasks = state["plan"].candidates
        if state["current_investigation"] >= len(tasks):
            return {"result": state["result"].model_copy(update={"termination_reason": self.stop or "investigations_completed"})}
        state = dict(state)
        if not state["initial_evidence_loaded"]:
            queries = self._initial_queries(self._current(state))
            if queries:
                return {"pending_queries": queries, "initial_evidence_loaded": True,
                    "model_calls": self.calls}
            state["initial_evidence_loaded"] = True
        turn = None
        deferred_count = len(self.deferred_stages)
        if not self.stop:
            turn = await self.call("investigate", state, ResponsibilityInvestigationTurn)
        if turn and turn.action == "tools":
            return {"pending_queries": turn.queries, "model_calls": self.calls}
        if turn and turn.conclusion is not None:
            return self._close_investigation(state, turn.conclusion)
        delivered = sorted((record for record in self.references() if record.id in self._delivered_ids(state)),
            key=lambda record: record.kind != "source")[:80]
        gaps = self._coverage_gap(state, self._current(state), delivered)
        if gaps and not state.get("coverage_recovery_done") and self.remaining_seconds() > 0:
            task = self._current(state)
            queries = []
            source = [record for record in delivered if record.kind == "source"]
            covered_end = max((record.end_line or 0) for record in source
                if record.path == task.primary_component) if source else 0
            target = next((item for item in self.tools.accessible_snapshot.files
                if item.path == task.primary_component), None)
            if target and target.line_count and covered_end < target.line_count and task.primary_component in self.config.tools:
                queries.append(ResponsibilityToolQuery(tool="get_source_excerpt",
                    arguments={"path": task.primary_component, "start_line": covered_end + 1,
                        "end_line": min(target.line_count, covered_end + 40)},
                    reason="Cover the remaining tail of the primary component."))
            queries.extend(self._initial_queries(task)[:1] if queries else [])
            if queries:
                return {"pending_queries": queries, "coverage_recovery_done": True,
                    "initial_evidence_loaded": True, "task_limitations": [*state["task_limitations"],
                        f"Coverage recovery requested: {', '.join(gaps[:2])}"],
                    "model_calls": self.calls}
        if self.stop == "model_or_schema_error" and len(self.deferred_stages) == deferred_count:
            self.stop = ""
        delivered = sorted((record for record in self.references() if record.id in self._delivered_ids(state)),
            key=lambda record: record.kind != "source")[:80]
        gaps = self._coverage_gap(state, self._current(state), delivered)
        conclusion = ResponsibilityInvestigationResult(
            investigation_id=self._current(state).id, status="inconclusive",
            summary="Investigation could not reach a supported conclusion.",
            justification=f"Execution stopped for this task: {self.stop or 'invalid_investigation_response'}.",
            components=list(dict.fromkeys(record.path for record in delivered))[:40],
            symbol_ids=list(dict.fromkeys(symbol for record in delivered if record.kind == "source" for symbol in record.symbol_ids))[:80],
            relationship_ids=list(dict.fromkeys(self._examined_relationships(state)))[:80],
            evidence_ids=[record.id for record in delivered],
            limitations=[self.stop or "invalid_investigation_response", *state["task_limitations"], *gaps])
        return self._close_investigation(state, conclusion)

    async def execute_investigation_tools(self, state):
        task = self._current(state)
        cache, keys = dict(state["query_cache"]), list(state["active_query_keys"])
        limitations = list(state["task_limitations"])
        failures = getattr(self, "_tool_failures", None)
        if failures is None:
            failures = self._tool_failures = {}
        for query in state["pending_queries"]:
            args, key = self._normalize_query(query, task)
            if failures.get(key, 0) >= 2:
                limitations.append("Tool query failed: retries_exhausted")
                continue
            cached = key in cache and cache[key].get("status") != "error"
            if cached:
                if key in keys:
                    keys.remove(key)
                keys.append(key)
                continue
            cache.pop(key, None)
            if self.remaining_seconds() <= 0:
                limitations.append("investigation_time_limit")
                break
            if len(self.references()) >= 400:
                limitations.append("evidence_ledger_limit")
                continue
            call_id = "responsibility-investigate-" + uuid4().hex
            try:
                response = self.tools.execute(query.tool, args, tool_call_id=call_id)
            except Exception as error:  # noqa: BLE001 - tool boundary
                view = {"status": "error", "tool_name": query.tool, "tool_call_id": call_id,
                    "error": {"code": "tool_execution_error", "message": safe_diagnostic(error)}, "evidence": []}
            else:
                view = self.tools.model_view(response) | {"tool_call_id": response.tool_call_id,
                    "snapshot_hash": response.snapshot_hash}
            if view["status"] != "error":
                cache[key] = view
                keys.append(key)
            else:
                failures[key] = failures.get(key, 0) + 1
                limitations.append("Tool query failed: " + view["error"]["code"])
        return {"query_cache": cache, "active_query_keys": keys, "pending_queries": [],
            "task_limitations": list(dict.fromkeys(limitations)),
            "tool_calls": self.tools.budget_usage.tool_calls, "evidence": self.references()}
