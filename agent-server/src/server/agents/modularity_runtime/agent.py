"""Independent, snapshot-bound LangGraph auditor. Clients remain caller-owned."""

import asyncio
import json
import math
from pathlib import Path
from time import monotonic
from uuid import uuid4

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from ...config.logs import get_logger
from ..repository_runtime.tools import TOOL_SCHEMAS, RepositoryToolset
from .provenance import matches_commit
from .provider import (
    ProviderPacer,
    RequestTokenQuotaExceeded,
    provider_diagnostic,
    retry_delay,
    transient,
)
from .schemas import (
    AuditRequest,
    AuditResult,
    Evaluation,
    EvidenceReference,
    Finding,
    FindingReview,
    InvestigationConfig,
    InvestigationPlan,
    Review,
)
from .state import InvestigationState
from .structured import finish_diagnostic, parse_structured, safe_diagnostic


def _unique(records, label):
    ids = [record.id for record in records]
    if len(ids) != len(set(ids)):
        raise ValueError(f"Duplicate {label} IDs.")


class InvestigationAgent:
    """Inject a native chat model, or an existing provider wrapper exposing `.llm`.

    Each run compiles its own graph and binds fresh read-only tools to the supplied
    RepositoryToolset. Use a fresh toolset per audit; no persistence or callbacks.
    """

    request_type = AuditRequest
    config_type = InvestigationConfig
    execution_type = None

    def __init__(self, model, config: InvestigationConfig | None = None, *, provider_pacer=None):
        self.model = getattr(model, "llm", model)
        self.config = config or self.config_type()
        self.provider_pacer = provider_pacer
        unknown = set(self.config.tools) - TOOL_SCHEMAS.keys()
        if unknown:
            raise ValueError(f"Unknown repository tools: {sorted(unknown)}")
        if len(self.config.tools) != len(set(self.config.tools)):
            raise ValueError("Tool names must be unique.")
        allowed = {"plan_investigation", "investigate", "evaluate_evidence", "review_findings"}
        if set(self.config.prompts) - allowed:
            raise ValueError("Prompt overrides must name cognitive nodes.")

    async def run(self, tools: RepositoryToolset, request: AuditRequest | None = None) -> AuditResult:
        request = request or self.request_type()
        _unique(request.criteria, "criterion")
        if tools.budget_usage.tool_calls:
            raise ValueError("Use a fresh RepositoryToolset for each audit.")
        execution = self.execution_type(self.model, self.config, tools, request)
        if self.provider_pacer is not None:
            execution.provider_pacer = self.provider_pacer
        state = await execution.graph.ainvoke(
            execution.initial_state(),
            {"recursion_limit": 4 * self.config.max_model_calls + 20},
        )
        return state["result"]


class InvestigationExecution:
    """The shared graph, budgets and evidence checks; specializations supply schemas/prompts."""

    trace_name = "modularity-investigation"
    tool_prefix = "modularity"
    prompt_directory: Path
    evaluation_schema = Evaluation
    finding_schema = Finding
    result_schema = AuditResult

    def __init__(self, model, config, tools, request):
        self.model, self.config, self.tools, self.request = model, config, tools, request
        self.started = monotonic()
        self.calls = self.tokens = self.estimates = 0
        self.stop = ""
        self.issues = []
        self.retryable_failure = False
        self.provider_pacer = ProviderPacer(rate_limits=config.provider_rate_limits, interval=config.provider_request_interval_seconds,
            max_retries=config.max_provider_retries, backoff=config.provider_retry_backoff_seconds)
        self.logger = get_logger(self.trace_name)
        self._commit_checks = {}
        budget = tools.context.input.budget
        self.call_limit = min(config.max_model_calls, budget.max_model_calls)
        if self.call_limit < 4:
            raise ValueError("The repository budget must permit at least four model calls.")
        self.tool_limit = min(config.max_tool_calls, budget.max_tool_calls)
        self.token_limit = min(config.max_total_tokens, budget.max_total_tokens,
                               budget.max_tokens_per_objective)
        self.output_limit = min(config.max_output_tokens, budget.max_output_tokens_per_call)
        self.invoke_options = {"max_tokens": self.output_limit}
        if isinstance(model, BaseChatModel):
            # include_raw uses a RunnableParallel: per-invoke kwargs may not reach
            # its model branch. Bind the hard output cap on a shallow model copy.
            for field in ("max_output_tokens", "max_tokens"):
                if field in type(model).model_fields:
                    configured_limit = getattr(model, field)
                    if configured_limit is not None:
                        self.output_limit = min(self.output_limit, configured_limit)
                    self.model = model.model_copy(update={field: self.output_limit})
                    # Gemini rejects call-time max_tokens as an extra SDK field.
                    # The provider-specific model field above already enforces it.
                    self.invoke_options = {}
                    break
        self.native_tools = [self._wrap(name) for name in config.tools]
        self.investigator = self.model.bind_tools(self.native_tools) if self.native_tools else self.model
        self.graph = self._build_graph()

    def _wrap(self, name):
        def execute(**arguments):
            if self.remaining_seconds() <= 0 or self.tools.budget_usage.tool_calls >= self.tool_limit:
                return json.dumps({"status": "error", "error": "audit_budget_exhausted"})
            response = self.tools.execute(name, arguments, tool_call_id=self.tool_prefix + "-" + uuid4().hex)
            return response.model_dump_json()

        return StructuredTool.from_function(
            func=execute, name=name, args_schema=TOOL_SCHEMAS[name],
            description={
                "list_files": "List bounded repository files/components; paginate results.",
                "find_symbols": "Find definitions and symbol IDs by name/file/kind.",
                "list_relationships": "Explore code graph edges by source/target IDs; not runtime proof.",
                "get_source_excerpt": "Read a bounded retained source excerpt with line provenance.",
                "search_repository_text": "Search retained source for references and configuration.",
                "get_evidence": "Retrieve a snapshot evidence record by ID.",
                "get_infrastructure": "Inspect bounded infrastructure records.",
            }[name],
        )

    def remaining_seconds(self):
        return min(
            self.config.timeout_seconds - (monotonic() - self.started),
            self.tools.context.input.budget.max_elapsed_seconds - self.tools.context.elapsed_seconds,
        )

    def references(self):
        snapshot = self.tools.accessible_snapshot
        files = {item.id: item for item in snapshot.files}
        result = []
        for record in self.tools.retrieved_evidence:
            source = files[record.file_id]
            result.append(EvidenceReference(
                **record.model_dump(exclude={"snapshot_evidence_ids"}),
                path=source.path, commit=snapshot.repository.commit,
                symbol_ids=[s.id for s in snapshot.symbols
                            if s.file_id == record.file_id and record.start_line is not None
                            and s.start_line <= record.end_line and s.end_line >= record.start_line],
            ))
        return result

    def initial_state(self):
        repository = self.tools.accessible_snapshot.repository
        return {
            "repository_id": repository.name, "commit": repository.commit,
            "objective": self.request.objective,
            "architectural_context": self.request.architectural_context,
            "criteria": [c.model_dump() for c in self.request.criteria],
            "plan": None, "hypotheses": [], "messages": [], "evidence": [], "evaluation": None,
            "missing_information": [], "review": None, "iterations": 0, "model_calls": 0,
            "tool_calls": 0, "termination_reason": "", "limitations": [],
            "limits": self.config.model_dump(),
        }

    def _context(self, state):
        snapshot = self.tools.accessible_snapshot
        # Small navigational inventory only: source is exclusively retrieved by tools.
        return {
            "repository": state["repository_id"], "commit": state["commit"],
            "snapshot_hash": snapshot.repository.snapshot_hash,
            "objective": state["objective"], "architectural_context": state["architectural_context"],
            "criteria": state["criteria"],
            "inventory": {"file_count": len(snapshot.files),
                          "projects": [p.model_dump() for p in snapshot.projects[:20]],
                          "directories": [d.path for d in snapshot.directories[:60]],
                          "omitted_directories": max(0, len(snapshot.directories) - 60)},
            "plan": state["plan"].model_dump() if state["plan"] else None,
            "hypotheses": [h.model_dump() for h in state["hypotheses"]],
            "evidence": [r.model_dump() for r in self.references()],
            "evaluation": state["evaluation"].model_dump() if state["evaluation"] else None,
            "missing_information": state["missing_information"],
            "remaining_tool_calls": max(0, self.tool_limit - self.tools.budget_usage.tool_calls),
        }

    async def call(self, node, state, schema=None):
        if self.stop:
            return None
        native = False
        model = self.investigator
        schema_text = json.dumps(schema.model_json_schema()) if schema else ""
        if schema:
            model = self.model
            factory = getattr(model, "with_structured_output", None)
            if callable(factory):
                try:
                    model = factory(self.structured_schema(schema), method="json_schema", include_raw=True)
                    native = True
                except NotImplementedError:
                    pass  # Simple test models/custom adapters can use validated JSON.
                except Exception as error:  # noqa: BLE001 - adapter configuration boundary
                    self.issues.append(f"{node}: structured_output_setup: {safe_diagnostic(error, schema)}{provider_diagnostic(error)}")
                    self.stop = "model_or_schema_error"
                    return None
        prompt = self.config.prompts.get(node)
        if prompt is None:
            prompt = (self.prompt_directory / f"{node}.md").read_text(encoding="utf-8")
        if schema and not native:
            prompt += "\nReturn only valid JSON matching this schema:\n" + schema_text
        messages = [SystemMessage(content=prompt),
                    HumanMessage(content=json.dumps(self._context(state), ensure_ascii=False))]
        # Keep conversational history separate from the authoritative provenance ledger.
        messages.extend(state["messages"])
        if schema:
            messages.append(HumanMessage(content=f"Now execute {node}. Return the requested JSON, no tools."))
        overhead = (schema_text if native else "") if schema else json.dumps(
            [t.args_schema.model_json_schema() for t in self.native_tools],
        )
        attempts = 1 + self.config.max_schema_retries if schema else 1
        reserved_calls = {"plan_investigation": 3, "evaluate_evidence": 1, "review_findings": 0}.get(node, 2)
        for attempt in range(attempts):
            response = await self.provider_request(model, messages, overhead, node, schema, reserved_calls)
            if self.stop:
                return None
            raw = response.get("raw") if isinstance(response, dict) else response
            if not schema:
                if isinstance(response, AIMessage):
                    return response
                self.issues.append(f"{node}: response_schema: expected AIMessage with native tool calls.")
                self.stop = "model_or_schema_error"
                return None
            try:
                return parse_structured(response, schema, native)
            except Exception as error:  # noqa: BLE001 - untrusted model output; never echo raw data
                diagnostic = safe_diagnostic(error, schema) + finish_diagnostic(raw)
                detail = f"{node}: response_schema attempt {attempt + 1}/{attempts}: {diagnostic}"
                self.logger.warning("%s", detail)
                self.issues.append(detail)
                if attempt + 1 < attempts:
                    messages.append(HumanMessage(content=(
                        f"The previous {node} response failed validation: {diagnostic}. "
                        "Regenerate the complete result according to the response schema. "
                        "Use the exact field names, types and enum values; include all required fields. "
                        "Keep the result concise enough for the output limit. Do not invent evidence or criteria."
                    )))
        self.stop = "model_or_schema_error"
        return None

    def structured_schema(self, schema):
        return schema

    async def provider_request(self, model, messages, overhead, node, schema, reserved_calls):
        for retry in range(self.config.max_provider_retries + 1):
            if self.calls >= self.call_limit - reserved_calls or self.remaining_seconds() <= 0:
                self.stop = "model_call_limit" if self.calls >= self.call_limit - reserved_calls else "time_limit"
                return None
            characters = len(json.dumps([m.model_dump() for m in messages], default=str)) + len(overhead)
            input_estimate = math.ceil(characters * 0.5)
            reserve = input_estimate + self.output_limit
            if characters > self.config.max_context_characters:
                self.stop = "context_limit"
                return None
            if input_estimate > self.tools.context.input.budget.max_input_tokens_per_call:
                self.stop = "input_token_limit"
                return None
            if self.tokens + reserve > self.token_limit:
                self.stop = "token_limit"
                return None
            try:
                async def wait_for_slot(reservation_tokens=reserve):
                    if isinstance(self.provider_pacer, ProviderPacer):
                        def on_wait(wait_seconds, reasons):
                            if "rpm" in reasons or "tpm" in reasons:
                                self.logger.warning("%s: provider_rate_limit_wait seconds=%g reasons=%s", node, wait_seconds, ",".join(reasons))
                        return await self.provider_pacer.acquire(reservation_tokens, on_wait=on_wait)
                    async with self.provider_pacer.lock:
                        await self.provider_pacer.wait()
                        self.provider_pacer.completed_attempt()
                    return None
                quota_reservation = await asyncio.wait_for(wait_for_slot(), self.remaining_seconds())
            except RequestTokenQuotaExceeded:
                self.stop = "provider_tpm_request_limit"
                self.issues.append(f"{node}: request token reservation exceeds configured provider TPM.")
                return None
            except TimeoutError:
                self.stop = "time_limit"
                return None
            self.calls += 1
            # Unknown/failed calls remain conservatively charged, including corrections.
            self.tokens += reserve
            self.estimates += reserve
            try:
                response = await asyncio.wait_for(
                    model.ainvoke(messages, **self.invoke_options), self.remaining_seconds(),
                )
            except Exception as error:  # noqa: BLE001 - provider boundary; cancellation propagates
                detail = f"{node}: provider_request: {safe_diagnostic(error, schema)}{provider_diagnostic(error)}"
                self.logger.warning("%s", detail)
                self.issues.append(detail)
                self.retryable_failure = transient(error)
                if self.retryable_failure:
                    delay = max(retry_delay(error), min(120, self.provider_pacer.backoff * 2 ** retry))
                    self.provider_pacer.next_allowed = max(self.provider_pacer.next_allowed, monotonic() + delay)
                    if (retry < self.config.max_provider_retries and delay < self.remaining_seconds()
                            and self.calls < self.call_limit - reserved_calls and self.tokens + reserve <= self.token_limit):
                        self.logger.warning("%s: provider_retry %s/%s; cooldown_seconds=%g", node,
                            retry + 1, self.config.max_provider_retries, delay)
                        continue
                self.stop = "time_limit" if isinstance(error, TimeoutError) else "model_or_schema_error"
                return None
            raw = response.get("raw") if isinstance(response, dict) else response
            usage = getattr(raw, "usage_metadata", None)
            if usage and isinstance(usage.get("input_tokens"), int) and isinstance(usage.get("output_tokens"), int):
                actual_tokens = usage["input_tokens"] + usage["output_tokens"]
                self.tokens += actual_tokens - reserve
                self.estimates -= reserve
                if quota_reservation is not None:
                    self.provider_pacer.settle(quota_reservation, actual_tokens)
            self.retryable_failure = False
            return response

    async def plan_investigation(self, state):
        plan = await self.call("plan_investigation", state, InvestigationPlan)
        if plan:
            try:
                _unique(plan.hypotheses, "hypothesis")
                criteria = {c.id for c in self.request.criteria}
                if any(h.criterion_id is not None and h.criterion_id not in criteria for h in plan.hypotheses):
                    raise ValueError("Unknown hypothesis criterion.")
            except ValueError as error:
                self.issues.append(str(error))
                self.stop = "invalid_plan"
                plan = None
        return {"plan": plan, "hypotheses": plan.hypotheses if plan else [], "model_calls": self.calls}

    async def investigate(self, state):
        # Always leave an evaluation and a critical review call available.
        if self.calls >= self.call_limit - 2 or self.tools.budget_usage.tool_calls >= self.tool_limit:
            return {"model_calls": self.calls}
        answer = await self.call("investigate", state)
        if answer is None:
            return {"model_calls": self.calls}
        remaining = self.tool_limit - self.tools.budget_usage.tool_calls
        if len(answer.tool_calls) > remaining:
            self.issues.append("Tool batch exceeded remaining allowance; only the bounded prefix was executed.")
            answer = answer.model_copy(update={"tool_calls": answer.tool_calls[:remaining]})
        return {"messages": [answer], "model_calls": self.calls}

    def route_investigation(self, state):
        last = state["messages"][-1] if state["messages"] else None
        if isinstance(last, AIMessage) and last.tool_calls and not self.stop:
            return "tools"
        return "evaluate_evidence"

    async def evaluate_evidence(self, state):
        evaluation = await self.call("evaluate_evidence", state, self.evaluation_schema)
        if evaluation:
            try:
                _unique(evaluation.hypotheses, "hypothesis")
                _unique(evaluation.candidates, "finding")
                if not {h.id for h in state["hypotheses"]} <= {h.id for h in evaluation.hypotheses}:
                    raise ValueError("Evaluation omitted prior hypotheses.")
                criteria = {c.id for c in self.request.criteria}
                if any(h.criterion_id is not None and h.criterion_id not in criteria for h in evaluation.hypotheses):
                    raise ValueError("Unknown evaluation criterion.")
            except ValueError as error:
                self.issues.append(str(error))
                self.stop = "invalid_evaluation"
                evaluation = None
        return {
            "evaluation": evaluation or state["evaluation"],
            "hypotheses": evaluation.hypotheses if evaluation else state["hypotheses"],
            "missing_information": evaluation.missing_information if evaluation else
                [*state["missing_information"], "A valid evidence evaluation could not be completed."],
            "iterations": state["iterations"] + 1, "model_calls": self.calls,
            "tool_calls": self.tools.budget_usage.tool_calls, "evidence": self.references(),
        }

    def is_sufficient(self, state):
        evaluation = state["evaluation"]
        reason = self.stop
        if not reason:
            if evaluation and evaluation.sufficient and not evaluation.missing_information:
                reason = "sufficient_evidence"
            elif state["iterations"] >= self.config.max_iterations:
                reason = "iteration_limit"
            elif self.tools.budget_usage.tool_calls >= self.tool_limit:
                reason = "tool_call_limit"
            elif self.calls >= self.call_limit - 2:
                reason = "model_call_limit"
            elif self.remaining_seconds() <= 0:
                reason = "time_limit"
        return "review_findings" if reason else "investigate"

    async def review_findings(self, state):
        reason = self.stop
        if not reason:
            evaluation = state["evaluation"]
            reason = ("sufficient_evidence" if evaluation and evaluation.sufficient and not evaluation.missing_information
                      else "iteration_limit" if state["iterations"] >= self.config.max_iterations
                      else "tool_call_limit" if self.tools.budget_usage.tool_calls >= self.tool_limit
                      else "model_call_limit")
        # Budget termination can still leave room for review; provider/schema failures do not.
        review = await self.call("review_findings", state, Review)
        if review:
            candidates = state["evaluation"].candidates if state["evaluation"] else []
            ids = [item.finding_id for item in review.findings]
            if len(ids) != len(set(ids)) or set(ids) != {c.id for c in candidates}:
                self.issues.append("Review must classify every candidate exactly once.")
                review = None
        return {"review": review, "termination_reason": self.stop or reason, "model_calls": self.calls}

    def verify_references(self, evidence):
        """Resolve commit attribution once per cited file, shared by specialized results."""
        snapshot = self.tools.accessible_snapshot
        source_files = {s.id: s for s in snapshot.files}
        for reference in evidence:
            if snapshot.repository.commit and reference.file_id not in self._commit_checks:
                self._commit_checks[reference.file_id] = matches_commit(
                    snapshot.repository, source_files[reference.file_id], self.remaining_seconds(),
                )
        mismatch = any(not self._commit_checks.get(r.file_id, True) for r in evidence)
        verified = [r.model_copy(update={"commit": None})
                    if not self._commit_checks.get(r.file_id, True) else r for r in evidence]
        return verified, mismatch

    def finalize(self, state):
        references = {r.id: r for r in self.references()}
        criteria = {c.id: c for c in self.request.criteria}
        reviews = {r.finding_id: r for r in state["review"].findings} if state["review"] else {}
        findings = []
        limitations = [
            "Narrative documentation is excluded by the existing repository access policy; supply architectural context and criteria explicitly.",
            "Snapshot code relationships are navigation hints, not complete runtime dependency evidence.",
            "Retained content hashes identify audited bytes; commit citations are checked against Git blob identities before acceptance.",
            *self.issues,
        ]
        if state["review"]:
            limitations.extend(state["review"].limitations)
        if not state["commit"]:
            limitations.append("Commit unavailable; references are bound only to the snapshot and content hashes.")
        evaluation = state["evaluation"]
        for candidate in evaluation.candidates if evaluation else []:
            criterion = criteria.get(candidate.criterion_id)
            review = reviews.get(candidate.id) or FindingReview(
                finding_id=candidate.id, status="insufficient_evidence", rationale="Critical review unavailable.",
                severity=candidate.severity, confidence=0,
            )
            evidence = [references[i] for i in dict.fromkeys(candidate.evidence_ids) if i in references]
            evidence, commit_mismatch = self.verify_references(evidence)
            if commit_mismatch:
                limitations.append(f"Candidate {candidate.id}: retained evidence could not be verified at commit {state['commit']}.")
            invalid = (criterion is None or len(evidence) != len(set(candidate.evidence_ids))
                       or not any(r.kind == "source" for r in evidence)
                       or candidate.kind == "violation" and criterion.origin != "explicit"
                       or commit_mismatch)
            if invalid:
                review = review.model_copy(update={"status": "insufficient_evidence", "confidence": 0,
                    "rationale": "Host validation failed: missing/unknown source evidence, commit mismatch or non-explicit violation criterion."})
            if criterion is None:
                limitations.append(f"Candidate {candidate.id} omitted: unknown architectural criterion.")
                continue
            severities = ["info", "low", "medium", "high", "critical"]
            findings.append(self.finding_schema(
                **candidate.model_dump(exclude={"severity", "confidence", "evidence_ids"}),
                severity=min((candidate.severity, review.severity), key=severities.index),
                confidence=min(candidate.confidence, review.confidence),
                evidence_ids=[r.id for r in evidence], criterion=criterion, evidence=evidence,
                validation_status=review.status, review_rationale=review.rationale,
            ))
        hypotheses = [h.model_copy(update={"status": "inconclusive"}) if h.status == "pending" else h
                      for h in state["hypotheses"]]
        if any(h.status == "inconclusive" for h in hypotheses):
            limitations.append("Some hypotheses remain inconclusive; absence of findings does not establish boundary compliance.")
        if not state["review"]:
            limitations.append("Critical review was not completed; no candidate is accepted.")
        result = self.result_schema(
            repository_id=state["repository_id"], commit=state["commit"],
            snapshot_hash=self.tools.context.input.snapshot_hash, objective=state["objective"],
            plan=state["plan"], findings=findings, hypotheses=hypotheses,
            missing_information=state["missing_information"], limitations=list(dict.fromkeys(limitations)),
            termination_reason=state["termination_reason"], model_calls=self.calls,
            tool_calls=self.tools.budget_usage.tool_calls, iterations=state["iterations"],
            accounted_tokens=self.tokens, estimated_tokens=self.estimates,
        )
        return {"result": result}

    def _build_graph(self):
        graph = StateGraph(InvestigationState)
        for name in ("plan_investigation", "investigate", "evaluate_evidence", "review_findings", "finalize"):
            graph.add_node(name, getattr(self, name))
        graph.add_node("tools", ToolNode(self.native_tools, handle_tool_errors=True))
        graph.add_edge(START, "plan_investigation")
        graph.add_edge("plan_investigation", "investigate")
        graph.add_conditional_edges("investigate", self.route_investigation,
                                   ["tools", "evaluate_evidence"])
        graph.add_edge("tools", "investigate")
        graph.add_conditional_edges("evaluate_evidence", self.is_sufficient,
                                   ["investigate", "review_findings"])
        graph.add_edge("review_findings", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile()
