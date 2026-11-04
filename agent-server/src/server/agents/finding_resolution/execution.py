"""Bounded investigation and evidence-grounded resolution evaluation."""

import json
import math
from pathlib import Path, PurePosixPath
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from server.config.token_budget import token_budget_exceeded
from server.contracts.audit import Consumption
from server.infrastructure.llm.diagnostics import provider_diagnostic, provider_status
from server.runtimes.investigation.agent import InvestigationExecution
from server.runtimes.investigation.structured import finish_diagnostic, parse_structured
from server.runtimes.invocation_reporting import phase_node
from server.runtimes.repository.tools import TOOL_SCHEMAS, tool_signatures

from .diagnostics import (
    DiagnosticLogger,
    error_details,
    failure_text,
    safe_arguments,
    safe_text,
)
from .schemas import (
    FindingEvaluationTurn,
    FindingInvestigation,
    FindingInvestigationTurn,
    FindingVerificationResult,
    VerificationPlan,
)
from .state import FindingResolutionState


class FindingResolutionExecution(InvestigationExecution):
    trace_name = "finding-resolution"
    tool_prefix = "finding-resolution"
    prompt_directory = Path(__file__).parent / "prompts"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = DiagnosticLogger(self.logger, {})
        self._diagnostics = []
        self._completed_records = []
        self._completed_results = []
        self._failed_finding_ids = set()
        self._evaluation_prompt = self.config.prompts.get("evaluate_resolution")
        if self._evaluation_prompt is None:
            self._evaluation_prompt = (self.prompt_directory / "evaluate_resolution.md").read_text(encoding="utf-8")

    def _diagnostic(self, category, issues, *, error_type=None, scope="finding", **details):
        event = {"finding_id": safe_text(self._diagnostic_state["finding"].id, 200), "node": self._diagnostic_node,
            "attempt": self._diagnostic_attempt, "category": category, "scope": scope,
            "model_calls": self.calls, "error_type": error_type, "issues": issues, **details}
        self._diagnostics.append(event)
        self.logger.extra["last_diagnostic"] = event
        self.logger.warning("finding_resolution_diagnostic %s", json.dumps(event, sort_keys=True),
            extra={"finding_resolution_diagnostic": event})

    async def call(self, node, state, schema=None, guidance=""):
        self._diagnostic_node, self._diagnostic_state, self._diagnostic_attempt = node, state, 0
        issue_start = len(self.issues)
        result = await super().call(node, state, schema, guidance)
        if result is None and any("structured_output_setup:" in item for item in self.issues[issue_start:]):
            issue = next(item for item in self.issues[issue_start:] if "structured_output_setup:" in item)
            error_type = issue.split("structured_output_setup: ", 1)[1].split(" ", 1)[0]
            self._diagnostic("generation", [{"field": "response_schema", "rule": "structured_output_setup_failed"}],
                scope="global", error_type=error_type, safe_detail=issue.split("structured_output_setup: ", 1)[1]
                    .replace("response unavailable or invalid", "structured_output_setup_failed"))
        return result

    def _reject(self, field, rule, message):
        self._diagnostic("agent_validation", [{"field": field, "rule": rule}], error_type="ValueError")
        raise ValueError(message)

    @property
    def closing_call_reserve(self):
        return 1 + self.config.max_schema_retries

    def _evaluation_tokens(self, state):
        context = self.model_context("investigate", state)
        record = state["investigation"]
        context.update(node="evaluate_resolution", investigation={"summary": record.summary,
            "stop_reason": record.stop_reason, "limitations": record.limitations} if record else None,
            return_to_investigation_allowed=False,
            remaining_evaluation_returns=max(0, self.config.max_evaluation_returns - state["evaluation_returns"]))
        characters = len(json.dumps(context)) + len(self._evaluation_prompt) + 2000
        characters += 2 * len(json.dumps(FindingEvaluationTurn.model_json_schema()))
        return math.ceil(characters * .5) + self.output_limit

    def closing_token_reserve(self, node, request_reserve):
        if node != "investigate":
            return 0
        reserve = self._evaluation_tokens(self._diagnostic_state)
        self._evaluation_token_hold = token_budget_exceeded(self.tokens + request_reserve + reserve, self.token_limit)
        return reserve

    def initial_state(self):
        return {"next_finding": 0, "finding": None, "finding_context": {}, "plans": [], "messages": [],
            "termination_reason": "", "limitations": [], "consumption": Consumption(), "deferred_stages": [],
            "plan": None, "investigations": [], "query_cache": {}, "pending_queries": [], "history": [],
            "investigation_turns": 0, "no_progress_turns": 0, "tool_stop": "",
            "finding_usage_start": Consumption(), "issue_start": 0, "investigation": None, "results": [],
            "evaluation_returns": 0, "evaluation_return": False, "missing_checks": []}

    def _build_graph(self):
        graph = StateGraph(FindingResolutionState)
        graph.add_node("read_finding", phase_node("read_finding", self.read_finding))
        graph.add_node("plan_verification", phase_node("plan_verification", self.plan_verification))
        graph.add_node("investigate", phase_node("investigate", self.investigate))
        graph.add_node("tools", phase_node("tools", self.execute_tools))
        graph.add_node("evaluate_resolution", phase_node("evaluate_resolution", self.evaluate_resolution))
        graph.add_edge(START, "read_finding")
        graph.add_conditional_edges("read_finding", lambda state: "plan" if state["finding"] else "end",
            {"plan": "plan_verification", "end": END})
        graph.add_conditional_edges("plan_verification", lambda state: "investigate" if state["plan"] else "evaluate_resolution",
            {"evaluate_resolution": "evaluate_resolution", "investigate": "investigate"})
        graph.add_conditional_edges("investigate", self.route_investigation,
            {"evaluate_resolution": "evaluate_resolution", "tools": "tools"})
        graph.add_edge("tools", "investigate")
        graph.add_conditional_edges("evaluate_resolution", self.route_evaluation,
            {"end": END, "investigate": "investigate", "next": "read_finding"})
        return graph.compile()

    def read_finding(self, state):
        index = state["next_finding"]
        if index >= len(self.request.findings):
            failed = bool(self._failed_finding_ids) or any(item.stop_reason == "model_or_schema_error" for item in state["investigations"])
            return {"finding": None, "finding_context": {}, "messages": [], "plan": None,
                "query_cache": {}, "pending_queries": [], "history": [], "investigation": None, "missing_checks": [],
                "termination_reason": ("investigations_completed_with_errors" if failed else "investigations_completed")
                    if index else "no_findings"}
        finding = self.request.findings[index].model_copy(deep=True)
        snapshot = self.tools.accessible_snapshot
        paths = {source.path for source in snapshot.files}
        return {"finding": finding, "messages": [], "plan": None, "query_cache": {}, "pending_queries": [],
            "history": [], "investigation_turns": 0, "no_progress_turns": 0, "tool_stop": "",
            "investigation": None, "evaluation_returns": 0, "evaluation_return": False, "missing_checks": [],
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
        context = {**state["finding_context"], "node": node,
            "plan": state["plan"].model_dump(mode="json") if state["plan"] else None,
            "current_evidence": [reference.model_dump(mode="json") for reference in self._current_references(state)],
            "tool_results": [self.tools.model_view(response) | {
                "tool_call_id": response.tool_call_id, "snapshot_hash": response.snapshot_hash}
                for response in state["query_cache"].values()],
            "history": [turn.model_dump(mode="json") for turn in state["history"]],
            "remaining_investigation_turns": self.config.max_iterations - state["investigation_turns"],
            "remaining_model_calls": None if math.isinf(self.call_limit) else max(0, self.call_limit - self.calls),
            "remaining_tool_calls": None if math.isinf(self.tool_limit) else max(0, self.tool_limit - self.tools.budget_usage.tool_calls),
            "verification_gaps": state["missing_checks"]}
        if node == "evaluate_resolution":
            record = state["investigation"]
            context["investigation"] = {"summary": record.summary, "stop_reason": record.stop_reason,
                "limitations": record.limitations} if record else None
            context["return_to_investigation_allowed"] = not self._return_blocker(state)
            context["remaining_evaluation_returns"] = max(0, self.config.max_evaluation_returns - state["evaluation_returns"])
        return context

    def prepare_structured_result(self, node, result, state):
        if result.finding_id != state["finding"].id:
            self._reject("finding_id", "current_finding_id", "Use the current finding_id.")
        if node == "evaluate_resolution":
            if result.action == "investigate":
                if result.result is not None or not result.missing_checks or not all(item.strip() for item in result.missing_checks):
                    self._reject("missing_checks", "concrete_checks_without_result", "Request concrete missing checks and result=null.")
                return result
            if result.result is None or result.missing_checks:
                self._reject("result", "record_requires_result", "Recording requires a result and missing_checks=[].")
            verdict = result.result
            if verdict.finding_id != state["finding"].id:
                self._reject("result.finding_id", "current_finding_id", "Use the current finding_id in the result.")
            current = {reference.id: reference for reference in self._current_references(state)}
            if set(verdict.evidence_ids) - current.keys():
                self._reject("result.evidence_ids", "current_finding_evidence_only", "Evaluation may cite only current evidence for this finding.")
            if verdict.status != "inconclusive":
                if not any(current[identifier].kind == "source" for identifier in verdict.evidence_ids):
                    self._reject("result.evidence_ids", "decisive_result_requires_source", "resolved/persists require cited current source.")
                if any(current[identifier].commit_verification == "unverified" for identifier in verdict.evidence_ids):
                    self._reject("result.evidence_ids", "verified_current_provenance", "Unverified commit attribution requires inconclusive.")
            return result
        if node == "investigate":
            current = {reference.id: reference for reference in self._current_references(state)}
            if set(result.evidence_ids) - current.keys():
                self._reject("evidence_ids", "current_finding_evidence_only",
                    "Cite only current evidence delivered to this finding, not historical or other finding IDs.")
            if result.action == "tools":
                if not result.queries:
                    self._reject("queries", "tools_requires_queries", "action=tools requires queries.")
                self._validate_queries(result.queries, [("queries", index) for index in range(len(result.queries))])
            elif result.queries:
                self._reject("queries", "close_requires_empty_queries", "action=close requires queries=[].")
            elif not any(current[identifier].kind == "source" for identifier in result.evidence_ids) and not any(
                    limitation.strip() for limitation in result.limitations):
                self._reject("evidence_ids", "source_or_concrete_limitation",
                    "Closing without cited current source requires a concrete limitation; missing code is not proof.")
            return result
        self._validate_queries([query for check in result.checks for query in check.queries],
            [("checks", index, "queries", query_index) for index, check in enumerate(result.checks)
                for query_index in range(len(check.queries))])
        return result

    def _validate_queries(self, queries, locations):
        identifiers = []
        for query, location in zip(queries, locations, strict=True):
            field = ".".join(map(str, location))
            if query.name not in self.config.tools:
                self._reject(field + ".name", "enabled_repository_tool", "Queries must use enabled repository tools.")
            try:
                TOOL_SCHEMAS[query.name].model_validate(query.arguments)
            except ValidationError as error:
                _, issues = error_details(error, TOOL_SCHEMAS[query.name], (*location, "arguments"))
                self._diagnostic("tool_arguments", issues, error_type="ValidationError", tool=query.name)
                raise
            identifiers.append(query.id)
        if len(identifiers) != len(set(identifiers)):
            self._reject("queries.id", "unique_query_ids", "Query IDs must be unique within a plan or turn.")

    async def plan_verification(self, state):
        plan = await self.call("plan_verification", state, VerificationPlan)
        if plan:
            self._trace(state, "verification_plan", original_violation=safe_text(state["finding"].description),
                checks=[{"index": index, "question": safe_text(check.question),
                    "persists_if": safe_text(check.persists_if), "resolved_if": safe_text(check.resolved_if)}
                    for index, check in enumerate(plan.checks)], criteria_review="generated_conditions_not_semantically_validated")
        return {"plans": [*state["plans"], plan] if plan else state["plans"], "plan": plan,
            "termination_reason": self.stop or "planning", "limitations": list(self.issues),
            "consumption": self._usage(),
            "deferred_stages": list(self.deferred_stages)}

    async def provider_request(self, model, messages, overhead, node, schema, reserved_calls):
        self._diagnostic_attempt += 1
        if node == "evaluate_resolution":
            reserved_calls = 0
        if node == "investigate":
            messages = [message.model_copy(update={"content":
                "Return the structured JSON, not native tool calls. action=tools requests read-only queries; "
                "the graph executes them and supplies their current evidence for the next investigate turn. "
                "action=close ends evidence collection, NOT resolution evaluation."})
                if message.type == "human" and message.content == "Now execute investigate. Return the requested JSON, no tools."
                else message for message in messages]
        delegate, execution = model, self
        class ObservedModel:
            async def ainvoke(self, *args, **kwargs):
                try:
                    return await delegate.ainvoke(*args, **kwargs)
                except Exception as error:
                    category, issues = error_details(error, schema)
                    if issues[0]["rule"] == "structured_response_parse_failed":
                        category, issues = "provider", [{"field": "provider_request", "rule": "provider_request_failed"}]
                    execution._diagnostic(category, issues, error_type=type(error).__name__, scope="global",
                        http_status=provider_status(error), provider_facts=provider_diagnostic(error).strip())
                    raise
        diagnostic_start = len(self._diagnostics)
        response = await super().provider_request(ObservedModel(), messages, overhead, node, schema, reserved_calls)
        if node == "investigate":
            # Only a received-but-invalid response is local to this finding.
            # A failed provider/budget admission on a later retry must stay global.
            self._investigation_response_received = response is not None and not self.stop
        elif node == "evaluate_resolution":
            self._evaluation_response_received = response is not None and not self.stop
        if response is None and self.stop and len(self._diagnostics) == diagnostic_start:
            resource = self.stop in {"model_call_limit", "time_limit", "context_limit", "input_token_limit",
                "token_limit", "audit_token_limit"}
            held = node == "investigate" and ((self.stop == "model_call_limit" and self.calls < self.call_limit)
                or (self.stop == "token_limit" and getattr(self, "_evaluation_token_hold", False)))
            self._diagnostic("resource_limit" if resource else "provider",
                [{"field": "budget" if resource else "provider_request", "rule": "evaluation_reserve" if held else self.stop}],
                scope="finding" if held else "global")
        if response is None and not self.stop and schema is not None:
            self._diagnostic("generation", [{"field": "response", "rule": "empty_provider_response"}])
        if response is not None and not self.stop and schema is not None:
            # Observe canonical structural errors without changing the response,
            # exception, retry feedback, accounting or validation performed by call().
            try:
                parse_structured(response, schema, isinstance(response, dict))
            except Exception as error:  # noqa: BLE001 - diagnostic only; the runtime validates independently
                category, issues = error_details(error, schema)
                raw = response.get("raw") if isinstance(response, dict) else response
                finish = finish_diagnostic(raw).removeprefix("; ")
                self._diagnostic("generation" if finish else category, issues,
                    error_type=type(error).__name__, generation_outcome=finish or None)
        return response

    def _usage(self):
        return Consumption(model_calls=self.calls, tool_calls=self.tools.budget_usage.tool_calls,
            accounted_tokens=self.tokens, estimated_tokens=self.estimates)

    def _current_references(self, state):
        delivered = {reference.id for response in state["query_cache"].values() for reference in response.evidence}
        ledger, _ = self.verify_references([reference for reference in self.references() if reference.id in delivered])
        return ledger

    def _trace(self, state, transition, **details):
        details = {key: safe_arguments(value) if key.endswith("arguments") else value for key, value in details.items()}
        node = ("evaluate_resolution" if transition.startswith("evaluate_resolution") else
            "plan_verification" if transition == "verification_plan" else "tools" if transition in {
            "tool_result", "tools->investigate", "source_range_adjusted", "source_range_recovery"} else "investigate")
        event = {"finding_id": safe_text(state["finding"].id, 200),
            "node": node, "transition": transition, **self._usage().model_dump(), **details}
        self.logger.info("finding_resolution_trace %s", json.dumps(event, sort_keys=True), extra={"finding_resolution_trace": event})

    def _finish(self, state, summary, reason, limitations=()):
        if reason == "model_or_schema_error":
            self._failed_finding_ids.add(state["finding"].id)
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
        records = [item for item in state["investigations"] if item.finding_id != record.finding_id]
        if state["investigation"]:
            record = record.model_copy(update={"limitations": list(dict.fromkeys([*state["investigation"].limitations, *limits]))})
        records.append(record)
        self._completed_records = records
        self._trace(state, "investigate->close", reason=reason, evidence_ids=[reference.id for reference in evidence],
            summary=safe_text(summary), limitations=[failure_text(item, self._diagnostics) for item in limits],
            finding_consumption=record.consumption.model_dump())
        return {"investigations": records, "investigation": record,
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
        self._evaluation_token_hold = False
        turn = await self.call("investigate", state, FindingInvestigationTurn)
        working = {**state, "investigation_turns": state["investigation_turns"] + 1}
        if turn is None:
            if self.stop == "model_call_limit" and self.calls < self.call_limit:
                self.stop, reason = "", "evaluation_call_reserve"
            elif self.stop == "token_limit" and self._evaluation_token_hold:
                self.stop, reason = "", "evaluation_token_reserve"
            else:
                reason = self.stop or "invalid_investigation_response"
            update = self._finish(working, "No valid investigation decision was available.", reason, [reason])
            if reason == "model_or_schema_error" and self._investigation_response_received:
                self.stop = ("model_call_limit" if self.calls >= self.call_limit else
                    "time_limit" if self.remaining_seconds() <= 0 else "")
                update["termination_reason"] = self.stop or reason
                if not self.stop:
                    self._trace(working, "investigate->evaluate_resolution", reason="recoverable_model_or_schema_error")
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
        files = {item.id: item.path for item in self.tools.accessible_snapshot.files}
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
                arguments=arguments, error_code=response.error.code if response.error else None,
                evidence_ids=[reference.id for reference in response.evidence],
                evidence=[{"id": reference.id, "path": safe_text(files.get(reference.file_id, "")),
                    "content_hash": reference.content_hash, "kind": reference.kind, "start_line": reference.start_line,
                    "end_line": reference.end_line} for reference in response.evidence])
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
        return "evaluate_resolution"

    def _return_blocker(self, state):
        if self.stop or state["tool_stop"]:
            return self.stop or state["tool_stop"]
        if state["evaluation_returns"] >= self.config.max_evaluation_returns:
            return "evaluation_return_limit"
        if state["investigation_turns"] >= self.config.max_iterations or state["no_progress_turns"] >= 2:
            return "investigation_iteration_or_progress_limit"
        if self.calls + 1 + self.closing_call_reserve > self.call_limit:
            return "insufficient_calls_for_investigation_and_evaluation"
        if self.tools.budget_usage.tool_calls >= self.tool_limit or self.remaining_seconds() <= 0:
            return "insufficient_tools_or_time"
        if token_budget_exceeded(self.tokens + 2 * self._evaluation_tokens(state), self.token_limit):
            return "insufficient_tokens_for_investigation_and_evaluation"
        return ""

    def _record_evaluation(self, state, result):
        records = list(state["investigations"])
        if state["investigation"]:
            usage, baseline = self._usage().model_dump(), state["finding_usage_start"].model_dump()
            record = state["investigation"].model_copy(update={
                "consumption": Consumption(**{key: usage[key] - baseline[key] for key in usage if key != "model_calls_estimated"}),
                "limitations": list(dict.fromkeys([*state["investigation"].limitations, *self.issues[state["issue_start"]:]]))})
            records = [record if item.finding_id == result.finding_id else item for item in records]
        else:
            record = None
        results = [*state["results"], result]
        self._completed_records, self._completed_results = records, results
        self._trace(state, "evaluate_resolution->record", status=result.status, reason=safe_text(result.reason), evidence_ids=result.evidence_ids)
        return {"results": results, "investigations": records, "investigation": record,
            "next_finding": state["next_finding"] + 1, "evaluation_return": False, "missing_checks": [],
            "consumption": self._usage(), "limitations": list(dict.fromkeys([*state["limitations"], *self.issues])),
            "termination_reason": self.stop or "finding_evaluated", "deferred_stages": list(self.deferred_stages)}

    def _inconclusive(self, state, reason):
        return FindingVerificationResult(finding_id=state["finding"].id, status="inconclusive", reason=reason,
            evidence_ids=[reference.id for reference in self._current_references(state)])

    async def evaluate_resolution(self, state):
        self.timing.check_cancellation()
        # A spent tool/retrieval allowance prevents further investigation, not
        # evaluation of source already collected. Other global stops remain fatal.
        prior_stop = self.stop
        tool_limits = {"tool_call_limit", "tool_budget_exhausted", "content_budget_exhausted"}
        if self.stop in tool_limits:
            self.stop = ""
        if self.stop or state["plan"] is None:
            self.stop = self.stop or prior_stop
            return self._record_evaluation(state, self._inconclusive(state,
                f"Evaluation unavailable: {self.stop or 'no_valid_verification_plan'}. No resolution can be established."))
        self._evaluation_response_received = False
        turn = await self.call("evaluate_resolution", state, FindingEvaluationTurn)
        if turn is None:
            reason = self.stop or "invalid_evaluation_response"
            self._failed_finding_ids.add(state["finding"].id)
            if reason == "model_or_schema_error" and self._evaluation_response_received:
                self.stop = "model_call_limit" if self.calls >= self.call_limit else "time_limit" if self.remaining_seconds() <= 0 else ""
            result = self._inconclusive(state, f"Evaluation failed ({reason}); no valid evidence-grounded decision was obtained.")
        elif turn.action == "investigate":
            blocker = prior_stop or self._return_blocker(state)
            if not blocker:
                self._trace(state, "evaluate_resolution->investigate", missing_checks=[safe_text(item) for item in turn.missing_checks])
                return {"evaluation_returns": state["evaluation_returns"] + 1, "evaluation_return": True,
                    "missing_checks": turn.missing_checks, "consumption": self._usage(), "termination_reason": "investigating"}
            result = self._inconclusive(state, "Missing checks could not be completed (" + blocker + "): " + "; ".join(turn.missing_checks))
        else:
            result = turn.result
        self.stop = self.stop or prior_stop
        return self._record_evaluation(state, result)

    def route_evaluation(self, state):
        if state["evaluation_return"]:
            return "investigate"
        return "end" if self.stop else "next"

    def log_summary(self, state=None, interrupted=None):
        records = state["investigations"] if state is not None else self._completed_records
        results = state["results"] if state is not None else self._completed_results
        completed = {item.finding_id for item in results}
        self.logger.info("finding_resolution_summary %s", json.dumps({
            "termination_reason": state["termination_reason"] if state is not None else interrupted,
            "global_stop": interrupted or self.stop or None,
            "evaluations": [item.model_dump(exclude={"reason", "finding_id"}) | {
                "finding_id": safe_text(item.finding_id, 200), "reason": safe_text(item.reason)} for item in results],
            "individual_results": [{"finding_id": safe_text(item.finding_id, 200), "stop_reason": item.stop_reason,
                "evidence_count": len(item.evidence), "tool_results": len(item.tool_results),
                "limitations": [failure_text(text, [event for event in self._diagnostics if event["finding_id"] == item.finding_id])
                    for text in item.limitations]} for item in records],
            "pending_finding_ids": [safe_text(item.id, 200) for item in self.request.findings if item.id not in completed],
            "individual_error_attempts": sum(item["scope"] == "finding" for item in self._diagnostics),
            "global_errors": [item for item in self._diagnostics if item["scope"] == "global"],
            "consumption": self._usage().model_dump()}, sort_keys=True))
