"""Bounded planning/investigation graph; no resolution evaluation yet."""

import json
import math
from pathlib import Path, PurePosixPath
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from server.contracts.audit import Consumption
from server.runtimes.investigation.agent import InvestigationExecution
from server.runtimes.invocation_reporting import phase_node
from server.runtimes.repository.tools import TOOL_SCHEMAS, tool_signatures

from .schemas import FindingInvestigation, FindingInvestigationTurn, VerificationPlan
from .state import FindingResolutionState


class FindingResolutionExecution(InvestigationExecution):
    trace_name = "finding-resolution"
    tool_prefix = "finding-resolution"
    prompt_directory = Path(__file__).parent / "prompts"

    @property
    def closing_call_reserve(self):
        return 0  # No evaluation/review nodes are implemented.

    def initial_state(self):
        return {"next_finding": 0, "finding": None, "finding_context": {}, "plans": [], "messages": [],
            "termination_reason": "", "limitations": [], "consumption": Consumption(), "deferred_stages": [],
            "plan": None, "investigations": [], "query_cache": {}, "pending_queries": [], "history": [],
            "investigation_turns": 0, "no_progress_turns": 0, "tool_stop": "",
            "finding_usage_start": Consumption(), "issue_start": 0}

    def _build_graph(self):
        graph = StateGraph(FindingResolutionState)
        graph.add_node("read_finding", phase_node("read_finding", self.read_finding))
        graph.add_node("plan_verification", phase_node("plan_verification", self.plan_verification))
        graph.add_node("investigate", phase_node("investigate", self.investigate))
        graph.add_node("tools", phase_node("tools", self.execute_tools))
        graph.add_edge(START, "read_finding")
        graph.add_conditional_edges("read_finding", lambda state: "plan" if state["finding"] else "end",
            {"plan": "plan_verification", "end": END})
        graph.add_conditional_edges("plan_verification", lambda state: "end" if self.stop else "investigate",
            {"end": END, "investigate": "investigate"})
        graph.add_conditional_edges("investigate", self.route_investigation,
            {"end": END, "tools": "tools", "next": "read_finding"})
        graph.add_edge("tools", "investigate")
        return graph.compile()

    def read_finding(self, state):
        index = state["next_finding"]
        if index >= len(self.request.findings):
            failed = any(item.stop_reason == "model_or_schema_error" for item in state["investigations"])
            return {"finding": None, "finding_context": {}, "messages": [], "plan": None,
                "query_cache": {}, "pending_queries": [], "history": [],
                "termination_reason": ("investigations_completed_with_errors" if failed else "investigations_completed")
                    if index else "no_findings"}
        finding = self.request.findings[index].model_copy(deep=True)
        snapshot = self.tools.accessible_snapshot
        paths = {source.path for source in snapshot.files}
        return {"finding": finding, "messages": [], "plan": None, "query_cache": {}, "pending_queries": [],
            "history": [], "investigation_turns": 0, "no_progress_turns": 0, "tool_stop": "",
            "finding_usage_start": self._usage(), "issue_start": len(self.issues), "finding_context": {
            "finding": finding.model_dump(mode="json"),
            "historical_evidence_only": True,
            "repository": {"path": self.request.repository_path, "snapshot_hash": snapshot.repository.snapshot_hash},
            "affected_paths": [{"path": path, "in_current_snapshot": path in paths} for path in finding.components],
            "tools": {name: signature for name, signature in tool_signatures().items() if name in self.config.tools},
        }}

    def model_context(self, node, state):
        if node == "plan_verification":
            return state["finding_context"]
        return {**state["finding_context"], "plan": state["plan"].model_dump(mode="json"),
            "current_evidence": [reference.model_dump(mode="json") for reference in self._current_references(state)],
            "tool_results": [self.tools.model_view(response) | {
                "tool_call_id": response.tool_call_id, "snapshot_hash": response.snapshot_hash}
                for response in state["query_cache"].values()],
            "history": [turn.model_dump(mode="json") for turn in state["history"]],
            "remaining_investigation_turns": self.config.max_iterations - state["investigation_turns"],
            "remaining_model_calls": None if math.isinf(self.call_limit) else max(0, self.call_limit - self.calls),
            "remaining_tool_calls": None if math.isinf(self.tool_limit) else max(0, self.tool_limit - self.tools.budget_usage.tool_calls)}

    def prepare_structured_result(self, node, result, state):
        if result.finding_id != state["finding"].id:
            raise ValueError("Use the current finding_id.")
        if node == "investigate":
            current = {reference.id: reference for reference in self._current_references(state)}
            if set(result.evidence_ids) - current.keys():
                raise ValueError("Cite only current evidence delivered to this finding, not historical or other finding IDs.")
            if result.action == "tools":
                if not result.queries:
                    raise ValueError("action=tools requires queries.")
                self._validate_queries(result.queries)
            elif result.queries:
                raise ValueError("action=close requires queries=[].")
            elif not any(current[identifier].kind == "source" for identifier in result.evidence_ids) and not any(
                    limitation.strip() for limitation in result.limitations):
                raise ValueError("Closing without cited current source requires a concrete limitation; missing code is not proof.")
            return result
        self._validate_queries([query for check in result.checks for query in check.queries])
        return result

    def _validate_queries(self, queries):
        identifiers = []
        for query in queries:
            if query.name not in self.config.tools:
                raise ValueError("Queries must use enabled repository tools.")
            TOOL_SCHEMAS[query.name].model_validate(query.arguments)
            identifiers.append(query.id)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Query IDs must be unique within a plan or turn.")

    async def plan_verification(self, state):
        plan = await self.call("plan_verification", state, VerificationPlan)
        return {"plans": [*state["plans"], plan] if plan else state["plans"], "plan": plan,
            "termination_reason": self.stop or "planning", "limitations": list(self.issues),
            "consumption": self._usage(),
            "deferred_stages": list(self.deferred_stages)}

    async def provider_request(self, model, messages, overhead, node, schema, reserved_calls):
        if node == "investigate":
            messages = [message.model_copy(update={"content":
                "Return the structured JSON, not native tool calls. action=tools requests read-only queries; "
                "the graph executes them and supplies their current evidence for the next investigate turn. "
                "action=close ends evidence collection, NOT resolution evaluation."})
                if message.type == "human" and message.content == "Now execute investigate. Return the requested JSON, no tools."
                else message for message in messages]
        response = await super().provider_request(model, messages, overhead, node, schema, reserved_calls)
        if node == "investigate":
            # Only a received-but-invalid response is local to this finding.
            # A failed provider/budget admission on a later retry must stay global.
            self._investigation_response_received = response is not None and not self.stop
        return response

    def _usage(self):
        return Consumption(model_calls=self.calls, tool_calls=self.tools.budget_usage.tool_calls,
            accounted_tokens=self.tokens, estimated_tokens=self.estimates)

    def _current_references(self, state):
        delivered = {reference.id for response in state["query_cache"].values() for reference in response.evidence}
        ledger, _ = self.verify_references([reference for reference in self.references() if reference.id in delivered])
        return ledger

    def _trace(self, state, transition, **details):
        self.logger.info("finding_resolution_trace %s", json.dumps({"finding_id": state["finding"].id,
            "transition": transition, **self._usage().model_dump(), **details}, sort_keys=True))

    def _finish(self, state, summary, reason, limitations=()):
        evidence = self._current_references(state)
        errors = [f"{response.tool_name}: {response.error.code}" for response in state["query_cache"].values() if response.error]
        limits = list(dict.fromkeys([*limitations, *errors, *self.issues[state["issue_start"]:]]))
        if any(reference.commit_verification == "unverified" for reference in evidence):
            limits.append("Some current snapshot evidence could not be attributed to the declared commit.")
        usage = self._usage().model_dump()
        baseline = state["finding_usage_start"].model_dump()
        record = FindingInvestigation(finding_id=state["finding"].id, finding=state["finding"], plan=state["plan"],
            summary=summary, stop_reason=reason, evidence=evidence, tool_results=list(state["query_cache"].values()),
            history=state["history"], limitations=limits,
            consumption=Consumption(**{key: usage[key] - baseline[key] for key in usage if key != "model_calls_estimated"}))
        self._trace(state, "investigate->close", reason=reason, evidence_ids=[reference.id for reference in evidence])
        return {"investigations": [*state["investigations"], record], "next_finding": state["next_finding"] + 1,
            "pending_queries": [], "history": state["history"], "investigation_turns": state["investigation_turns"],
            "consumption": self._usage(), "termination_reason": self.stop or reason,
            "limitations": list(dict.fromkeys([*state["limitations"], *limits])), "deferred_stages": list(self.deferred_stages)}

    async def investigate(self, state):
        self.timing.check_cancellation()
        if self.remaining_seconds() <= 0:
            self.stop = "time_limit"
        elif self.calls >= self.call_limit:
            self.stop = "model_call_limit"
        reason = self.stop or state["tool_stop"]
        if state["investigation_turns"] >= self.config.max_iterations:
            reason = reason or "investigation_iteration_limit"
        if state["no_progress_turns"] >= 2:
            reason = reason or "no_investigation_progress"
        if reason:
            return self._finish(state, "Evidence collection stopped before another model decision.", reason, [reason])
        self._investigation_response_received = False
        turn = await self.call("investigate", state, FindingInvestigationTurn)
        working = {**state, "investigation_turns": state["investigation_turns"] + 1}
        if turn is None:
            reason = self.stop or "invalid_investigation_response"
            update = self._finish(working, "No valid investigation decision was available.", reason, [reason])
            if reason == "model_or_schema_error" and self._investigation_response_received:
                self.stop = ("model_call_limit" if self.calls >= self.call_limit else
                    "time_limit" if self.remaining_seconds() <= 0 else "")
                update["termination_reason"] = self.stop or reason
                if not self.stop:
                    self._trace(working, "investigate->read_finding", reason="recoverable_model_or_schema_error")
            return update
        working["history"] = [*state["history"], turn]
        self._trace(working, "llm->decision", action=turn.action,
            delivered_evidence_ids=[reference.id for reference in self._current_references(state)])
        if turn.action == "close":
            return self._finish(working, turn.summary,
                "investigation_limited" if turn.limitations else "evidence_collected", turn.limitations)
        self._trace(working, "investigate->tools", queries=len(turn.queries))
        return {"pending_queries": turn.queries, "history": working["history"],
            "investigation_turns": working["investigation_turns"], "consumption": self._usage()}

    def _valid_source_range(self, arguments):
        """Correct only out-of-content ranges; shared tools still enforce access."""
        path = arguments["path"].replace("\\", "/").removeprefix("./")
        source = next((item for item in self.tools.accessible_snapshot.files if item.path == path), None)
        if source is None or not source.line_count:
            return arguments
        start, end = arguments["start_line"], arguments["end_line"]
        if start > source.line_count:
            # Read a real initial window, never pretend the requested location exists.
            return arguments | {"start_line": 1, "end_line": None}
        if end is not None and end < start:
            return arguments | {"end_line": None}
        if end is not None and end > source.line_count:
            return arguments | {"end_line": min(source.line_count, start + self.tools.limits.max_source_lines - 1)}
        return arguments

    def execute_tools(self, state):
        cache = dict(state["query_cache"])
        executed, stop = 0, ""
        # At most one recovery per requested query, in this same tools node.
        pending = [(query.name, query.arguments, False) for query in state["pending_queries"]]
        while pending:
            self.timing.check_cancellation()
            name, requested, recovery = pending.pop(0)
            arguments = TOOL_SCHEMAS[name].model_validate(requested).model_dump(mode="json")
            if name == "get_source_excerpt":
                corrected = self._valid_source_range(arguments)
                if corrected != arguments:
                    self._trace(state, "source_range_adjusted", requested_arguments=arguments, effective_arguments=corrected)
                    arguments = corrected
            key = json.dumps([name, arguments], sort_keys=True)
            cached = key in cache
            if not cached:
                if self.remaining_seconds() <= 0:
                    stop = self.stop = "time_limit"
                    break
                if self.tools.budget_usage.tool_calls >= self.tool_limit:
                    stop = self.stop = "tool_call_limit"
                    break
                cache[key] = self.tools.execute(name, arguments,
                    tool_call_id=self.tool_prefix + "-" + uuid4().hex)
                executed += 1
            response = cache[key]
            self._trace(state, "tool_result", tool=name, cached=cached,
                tool_call_id=response.tool_call_id, snapshot_hash=response.snapshot_hash, status=response.status,
                evidence_ids=[reference.id for reference in response.evidence])
            if response.error and response.error.code in {"time_budget_exhausted", "tool_budget_exhausted", "content_budget_exhausted"}:
                stop = self.stop = response.error.code
                break
            if name == "get_source_excerpt" and response.error and response.error.code == "invalid_source_range" and not recovery:
                corrected = arguments | {"start_line": 1, "end_line": None}
                if corrected != arguments:
                    alternative = (name, corrected, True)
                elif "search_repository_text" in self.config.tools:
                    term = PurePosixPath(arguments["path"].replace("\\", "/")).stem[:1000]
                    if not term:
                        continue
                    alternative = ("search_repository_text", {"query": term,
                        "limit": min(10, self.tools.limits.max_metadata_items)}, True)
                else:
                    continue
                self._trace(state, "source_range_recovery", failed_tool_call_id=response.tool_call_id,
                    tool=alternative[0], arguments=alternative[1])
                pending.insert(0, alternative)
        self._trace(state, "tools->investigate", executed=executed)
        return {"query_cache": cache, "pending_queries": [], "tool_stop": stop,
            "no_progress_turns": 0 if executed else state["no_progress_turns"] + 1, "consumption": self._usage()}

    def route_investigation(self, state):
        if state["pending_queries"]:
            return "tools"
        return "end" if self.stop else "next"
