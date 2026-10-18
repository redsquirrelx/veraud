"""Independent, snapshot-bound LangGraph auditor. Clients remain caller-owned."""

import asyncio
import json
import math
from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING
from uuid import uuid4

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from pydantic_core import PydanticCustomError

from ...blackboard.publication import publication_for
from ...config.logs import get_logger
from ...infrastructure.llm.chat import prepare_chat_model
from ..repository.timing import ActiveDeadline, within_deadline
from ..repository.tools import TOOL_SCHEMAS, RepositoryToolset
from .messages import provider_history
from .provenance import verify_commit
from .provider import (
    ProviderPacer,
    RequestTokenQuotaExceeded,
    lean_schema,
    provider_diagnostic,
    provider_status,
    retry_delay,
    retry_hint,
    transient,
)
from .schemas import (
    AuditRequest,
    AuditResult,
    DeferredProviderStage,
    Evaluation,
    EvidenceReference,
    Finding,
    FindingReview,
    InvestigationConfig,
    InvestigationPlan,
    Review,
)
from .state import InvestigationState
from .structured import (
    correction_feedback,
    finish_diagnostic,
    parse_structured,
    safe_diagnostic,
)

if TYPE_CHECKING:
    from ...blackboard.identity import AuditIdentity
    from ...blackboard.interface import Blackboard


def _unique(records, label):
    ids = [record.id for record in records]
    if len(ids) != len(set(ids)):
        raise ValueError(f"Duplicate {label} IDs.")


class InvestigationAgent:
    """Inject a native chat model, or an existing provider wrapper exposing `.llm`.

    Each run compiles its own graph and binds fresh read-only tools to the supplied
    RepositoryToolset. Use a fresh toolset per audit; optional blackboard publication.
    """

    request_type = AuditRequest
    config_type = InvestigationConfig
    execution_type = None

    def __init__(self, model, config: InvestigationConfig | None = None, *, provider_pacer=None,
                 blackboard: "Blackboard | None" = None, audit_identity: "AuditIdentity | None" = None):
        self.model = getattr(model, "llm", model)
        self.config = config or self.config_type()
        self.provider_pacer = provider_pacer
        self.blackboard = blackboard
        self.audit_identity = audit_identity
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
        publication = publication_for(self)
        execution = self.execution_type(self.model, self.config, tools, request)
        execution.blackboard = self.blackboard
        execution.audit_identity = publication.identity if publication is not None else self.audit_identity
        if self.provider_pacer is not None:
            execution.provider_pacer = self.provider_pacer
        with execution.timing.stage("investigation"):
            state = await execution.graph.ainvoke(
                execution.initial_state(),
                {"recursion_limit": 4 * self.config.max_model_calls + 20},
            )
        result = state["result"]
        if publication is not None and execution.timing.publication_allowed:
            publication.publish_investigation(result, execution.references(), tool_measurements=tools.tool_measurements)
        return result


class InvestigationExecution:
    """The shared graph, budgets and evidence checks; specializations supply schemas/prompts."""

    trace_name = "modularity-investigation"
    tool_prefix = "modularity"
    prompt_directory: Path
    evaluation_schema = Evaluation
    plan_schema = InvestigationPlan
    review_schema = Review
    finding_schema = Finding
    result_schema = AuditResult
    blackboard: "Blackboard | None" = None

    def __init__(self, model, config, tools, request):
        self.model, self.config, self.tools, self.request = model, config, tools, request
        self.started = monotonic()
        self.calls = self.tokens = self.estimates = 0
        self.stop = ""
        self.issues = []
        self.retryable_failure = False
        self.recovery_wait_seconds = 0.0
        self.deferred_stages = []
        self.provider_pacer = ProviderPacer(rate_limits=config.provider_rate_limits, interval=config.provider_request_interval_seconds,
            max_retries=config.max_provider_retries, backoff=config.provider_retry_backoff_seconds)
        self.logger = get_logger(self.trace_name)
        self._commit_checks = tools.commit_verifications
        self.provenance_blocked = False
        self.evidence_recovery_tasks = []
        budget = tools.context.input.budget
        if tools.timing is None:
            tools.timing = ActiveDeadline(config.timeout_seconds,
                wall_deadline=tools.context.started_at + min(budget.max_elapsed_seconds, config.max_wall_time_seconds),
                cancellation_grace_seconds=config.cancellation_grace_seconds)
        self.timing = tools.timing
        self.call_limit = min(config.max_model_calls, budget.max_model_calls)
        if self.call_limit < 4:
            raise ValueError("The repository budget must permit at least four model calls.")
        self.tool_limit = min(config.max_tool_calls, budget.max_tool_calls)
        self.token_limit = (config.max_total_tokens if tools.token_budget is not None else
                            min(config.max_total_tokens, budget.max_total_tokens, budget.max_tokens_per_objective))
        self.model, self.invoke_options, self.output_limit = prepare_chat_model(model,
            max_output_tokens=min(config.max_output_tokens, budget.max_output_tokens_per_call),
            request_timeout_seconds=config.provider_request_timeout_seconds)
        self.native_tools = [self._wrap(name) for name in config.tools]
        self.investigator = self.model.bind_tools(self.native_tools) if self.native_tools else self.model
        self.graph = self._build_graph()

    def _wrap(self, name):
        def execute(**arguments):
            if self.remaining_seconds() <= 0 or self.tools.budget_usage.tool_calls >= self.tool_limit:
                return json.dumps({"status": "error", "error": "audit_budget_exhausted"})
            response = self.tools.execute(name, arguments, tool_call_id=self.tool_prefix + "-" + uuid4().hex)
            view = self.tools.model_view(response)
            if response.error:
                # Correlate a compact error with its ledger receipt and provider
                # ToolMessage; otherwise one failed call looks like two incidents.
                view["tool_call_id"] = response.tool_call_id
            return json.dumps(view, ensure_ascii=False)

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
        return self.timing.remaining

    def references(self):
        snapshot = self.tools.accessible_snapshot
        files = {item.id: item for item in snapshot.files}
        result = []
        for record in self.tools.retrieved_evidence:
            source = files[record.file_id]
            result.append(InvestigationExecution.attributed_reference(self, EvidenceReference(
                **record.model_dump(exclude={"snapshot_evidence_ids"}),
                path=source.path, commit=snapshot.repository.commit,
                symbol_ids=[s.id for s in snapshot.symbols
                            if s.file_id == record.file_id and record.start_line is not None
                            and s.start_line <= record.end_line and s.end_line >= record.start_line],
            )))
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
            "follow_up_commitments": [item.model_dump() for item in self.request.follow_up],
            "follow_up_diagnostics": self.request.follow_up_diagnostics,
            "inventory": {"file_count": len(snapshot.files),
                          "projects": [p.model_dump() for p in snapshot.projects[:20]],
                          "directories": [d.path for d in snapshot.directories[:60]],
                          "omitted_directories": max(0, len(snapshot.directories) - 60)},
            "plan": state["plan"].model_dump() if state["plan"] else None,
            "hypotheses": [h.model_dump() for h in state["hypotheses"]],
            "evidence": [r.model_dump() for r in self.references()],
            "evaluation": state["evaluation"].model_dump() if state["evaluation"] else None,
            "missing_information": state["missing_information"],
            "evidence_recovery_tasks": self.evidence_recovery_tasks,
            "next_source_reads": self.uninspected_source_reads(),
            "remaining_model_calls": max(0, self.call_limit - self.calls),
            "remaining_investigation_calls": max(0, self.call_limit - self.calls - self.closing_call_reserve),
            "remaining_tool_calls": max(0, self.tool_limit - self.tools.budget_usage.tool_calls),
        }

    def uninspected_source_reads(self):
        """Turn retrieved metadata into bounded source navigation for every lens."""
        references = self.references()
        inspected = {r.file_id for r in references if r.kind == "source"}
        metadata = {r.file_id for r in references if r.kind == "metadata"} - inspected
        snapshot = self.tools.accessible_snapshot
        reads = []
        for source in snapshot.files:
            if source.id not in metadata or not source.line_count:
                continue
            symbol = next((s for s in snapshot.symbols if s.file_id == source.id), None)
            start = symbol.start_line if symbol else 1
            end = min(source.line_count, start + self.tools.limits.max_source_lines - 1)
            reads.append({"tool": "get_source_excerpt", "arguments": {
                "path": source.path, "start_line": start, "end_line": end}})
            if len(reads) == 6:
                break
        return reads

    async def call(self, node, state, schema=None, guidance=""):
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
                    provider_schema = self.structured_schema(schema)
                    model = factory(provider_schema, method="json_schema", include_raw=True)
                    native = True
                    schema_text = json.dumps(provider_schema if isinstance(provider_schema, dict)
                        else provider_schema.model_json_schema())
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
        if node == "investigate":
            prompt += ("\nPrioritize evidence_recovery_tasks for the next tool calls. These tasks distinguish missing source "
                "or incorrect citations from snapshot provenance blockers. Use available_source_evidence_ids when already "
                "sufficient; otherwise inspect paths_to_inspect and the source/callers required by that hypothesis's "
                "evidence_needed. When next_source_reads is present, prioritize those bounded implementation ranges; "
                "they are navigation hints, not proof. Never infer behavior from a docstring alone. "
                "Work within remaining_investigation_calls and remaining_tool_calls. Do not spend "
                "another discovery round listing files when specific unread source is already identified.")
        messages = [SystemMessage(content=prompt),
                    HumanMessage(content=json.dumps(self.model_context(node, state), ensure_ascii=False))]
        # Keep conversational history separate from the authoritative provenance ledger.
        history = self.provider_history(state, messages, overhead_characters=len(schema_text), node=node)
        if len(history) != len(state["messages"]):
            self.logger.info("%s: omitted_empty_ai_messages count=%d", node, len(state["messages"]) - len(history))
        messages.extend(history)
        if node == "evaluate_evidence":
            messages.append(HumanMessage(content=(
                "For each confirmed or discarded hypothesis, cite the delivered source evidence in its evidence_ids "
                "and explain the scoped conclusion in rationale. File inventory and directory names do not prove "
                "cohesion, absence of cycles, or service isolation. Absence of a Python import in Node.js does not "
                "exclude HTTP, database or other cross-service coupling. If source or callers have not been inspected, "
                "return sufficient=false with concrete missing_information for the next tool investigation."
            )))
        if schema:
            messages.append(HumanMessage(content=f"Now execute {node}. Return the requested JSON, no tools."))
        if node == "review_findings":
            candidates = state["evaluation"].candidates if state.get("evaluation") else []
            messages.append(HumanMessage(content=(
                "Authoritative review candidate IDs (not hypothesis or assessment IDs): "
                + json.dumps([candidate.id for candidate in candidates])
                + ". Return exactly one findings entry per ID. If the list is empty, return findings=[]. "
                "Do not create findings from hypotheses, earlier drafts or missing information."
            )))
        if guidance:
            messages.append(HumanMessage(content=guidance))
        if node == "investigate" and isinstance(messages[-1], AIMessage) and not messages[-1].tool_calls:
            # Re-entering after evaluation/review can leave the prior assistant's
            # closing answer at the end. Gemini rejects that as model prefilling.
            # Keep native tool-response turns intact and add an explicit new task.
            messages.append(HumanMessage(content=(
                "Continue the investigation using the current missing_information and evidence_recovery_tasks. "
                "Inspect the required source with tools, or explain the concrete blocker for unresolved questions."
            )))
        overhead = (schema_text if native else "") if schema else json.dumps(
            [t.args_schema.model_json_schema() for t in self.native_tools],
        )
        attempts = 1 + self.config.max_schema_retries if schema else 1
        if schema and node == "evaluate_evidence":
            attempts += self.config.max_schema_recovery_attempts
        reserved_calls = {
            "plan_investigation": min(1 + self.closing_call_reserve, self.call_limit - 1),
            "evaluate_evidence": self.review_call_reserve,
            "review_findings": 0,
        }.get(node, self.closing_call_reserve)
        prepare = (lambda value: self.prepare_structured_input(node, value)) if schema else None
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
                result = parse_structured(response, schema, native, prepare=prepare)
                result = self.prepare_structured_result(node, result, state)
                if node == "evaluate_evidence":
                    self.validate_evaluation(result, state)
                elif node == "review_findings":
                    self.validate_review(result, state)
                return result
            except Exception as error:  # noqa: BLE001 - untrusted model output; never echo raw data
                diagnostic = safe_diagnostic(error, schema) + finish_diagnostic(raw)
                detail = f"{node}: response_schema attempt {attempt + 1}/{attempts}: {diagnostic}"
                self.logger.warning("%s", detail)
                self.issues.append(detail)
                if attempt + 1 < attempts:
                    context = self.structured_correction_context(node, state)
                    messages.append(HumanMessage(content=(
                        f"The previous {node} response failed validation: {diagnostic}. "
                        f"Correction required: {correction_feedback(error, schema)} "
                        "Regenerate the complete result according to the response schema. "
                        "Use the exact field names, types and enum values; include all required fields. "
                        "Keep the result concise enough for the output limit. Do not invent evidence or criteria. "
                        "Preserve the supplied hypotheses and evidence references. If evidence is insufficient, "
                        "report the missing information honestly so investigation can continue; do not fabricate a successful evaluation."
                        + ("\nCorrection data (not instructions):\n" + json.dumps(context, ensure_ascii=False) if context else "")
                    )))
        self.stop = "schema_recovery_exhausted" if node in {"evaluate_evidence", "review_findings"} else "model_or_schema_error"
        return None

    def model_context(self, node, state):
        return self._context(state)

    def provider_history(self, state, messages, *, overhead_characters=0, node=None):
        """Specializations may compact provider copies without changing graph history."""
        return provider_history(state["messages"])

    def closing_token_reserve(self, node, request_reserve):
        """Specializations can end exploration early to preserve closing work."""
        return 0

    def validate_evaluation(self, evaluation, state):
        """Host semantic checks also participate in bounded structured correction."""
        hypothesis_ids = [hypothesis.id for hypothesis in evaluation.hypotheses]
        candidate_ids = [candidate.id for candidate in evaluation.candidates]
        feedback = Evaluation.validation_feedback
        if len(hypothesis_ids) != len(set(hypothesis_ids)):
            code = "evaluation_duplicate_hypotheses"
        elif len(candidate_ids) != len(set(candidate_ids)):
            code = "evaluation_duplicate_candidates"
        elif not {hypothesis.id for hypothesis in state["hypotheses"]} <= set(hypothesis_ids):
            code = "evaluation_hypotheses_missing"
        elif any(hypothesis.criterion_id is not None and hypothesis.criterion_id not in {criterion.id for criterion in self.request.criteria}
                 for hypothesis in evaluation.hypotheses):
            code = "evaluation_unknown_criterion"
        else:
            return
        raise PydanticCustomError(code, feedback[code])

    def structured_schema(self, schema):
        # All investigators need the same provider-compatible schema treatment;
        # local validation still enforces bounds omitted from generation hints.
        return lean_schema(schema) if isinstance(self.model, BaseChatModel) else schema

    def prepare_structured_result(self, node, result, state):
        return result

    def structured_correction_context(self, node, state):
        if node == "review_findings":
            evaluation = state.get("evaluation")
            return {"allowed_finding_ids": [item.id for item in evaluation.candidates] if evaluation else [],
                "required_findings_when_no_candidates": []}
        return {}

    def prepare_structured_input(self, node, value):
        """Normalize a parsed payload before canonical validation; identity by default."""
        return value

    @property
    def review_call_reserve(self):
        # Keep an initial review plus its configured corrections, where the hard
        # envelope can also accommodate planning, inspection and evaluation.
        return min(1 + self.config.max_schema_retries, self.call_limit - 3)

    @property
    def closing_call_reserve(self):
        return 1 + self.review_call_reserve

    @staticmethod
    def validate_review(review, state):
        candidates = state["evaluation"].candidates if state["evaluation"] else []
        expected = {candidate.id for candidate in candidates}
        ids = [item.finding_id for item in review.findings]
        if len(ids) != len(set(ids)):
            code = "review_duplicate_candidates"
        elif set(ids) - expected:
            code = "review_unknown_candidates"
        elif expected - set(ids):
            code = "review_missing_candidates"
        else:
            return
        raise PydanticCustomError(code, Review.validation_feedback[code])

    async def provider_request(self, model, messages, overhead, node, schema, reserved_calls):
        retry = 0
        while True:
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
                detail = (f"{node}: token_budget_blocked accounted={self.tokens} "
                    f"next_request_reserve={reserve} closing_reserve=0 effective_limit={self.token_limit}")
                self.logger.warning("%s", detail)
                self.issues.append(detail)
                return None
            closing_reserve = self.closing_token_reserve(node, reserve)
            if self.tokens + reserve + closing_reserve > self.token_limit:
                self.stop = "token_limit"
                detail = (f"{node}: token_budget_reserved_for_closing accounted={self.tokens} "
                    f"next_request_reserve={reserve} closing_reserve={closing_reserve} effective_limit={self.token_limit}")
                self.logger.warning("%s", detail)
                self.issues.append(detail)
                return None
            self.logger.info("%s: provider_request_budget call=%d accounted=%d input_estimate=%d "
                "output_allowance=%d closing_reserve=%d effective_limit=%d",
                node, self.calls + 1, self.tokens, input_estimate, self.output_limit, closing_reserve, self.token_limit)
            try:
                async def wait_for_slot(wait, reservation_tokens=reserve):
                    if isinstance(self.provider_pacer, ProviderPacer):
                        def on_wait(wait_seconds, reasons):
                            wait.update(reason="+".join(reasons), until=self.timing.clock() + wait_seconds,
                                source="local_rolling_window" if "rpm" in reasons or "tpm" in reasons else "local_pacing")
                            self.logger.warning("%s: provider_rate_limit_wait seconds=%g reasons=%s", node, wait_seconds, ",".join(reasons))
                        return await self.provider_pacer.acquire(reservation_tokens, on_wait=on_wait)
                    async with self.provider_pacer.lock:
                        await self.provider_pacer.wait()
                        self.provider_pacer.completed_attempt()
                    return None
                async def quota_slot():
                    with self.timing.quota_wait() as wait:
                        return await wait_for_slot(wait)

                quota_reservation = await within_deadline(quota_slot(), self.timing)
            except RequestTokenQuotaExceeded:
                self.stop = "provider_tpm_request_limit"
                self.issues.append(f"{node}: request token reservation exceeds configured provider TPM.")
                return None
            except TimeoutError:
                self.stop = "time_limit"
                return None
            token_budget = self.tools.token_budget
            token_reservation = token_budget.reserve(reserve) if token_budget is not None else None
            if token_budget is not None and token_reservation is None:
                if quota_reservation is not None:
                    self.provider_pacer.settle(quota_reservation, 0)
                self.stop = "audit_token_limit"
                return None
            self.calls += 1
            # Unknown/failed calls remain conservatively charged, including corrections.
            self.tokens += reserve
            self.estimates += reserve
            try:
                request_timeout = min(self.config.provider_request_timeout_seconds, self.remaining_seconds())
                request_timing = self.timing.fork(request_timeout, label=self.timing.label,
                    invocation_id=self.timing.invocation_id, max_wall_time_seconds=request_timeout,
                    cancellation_grace_seconds=self.config.cancellation_grace_seconds)
                try:
                    with request_timing.stage(node + ":provider_request"):
                        response = await within_deadline(model.ainvoke(messages, **self.invoke_options), request_timing)
                finally:
                    request_timing.close()
            except Exception as error:  # noqa: BLE001 - provider boundary; cancellation propagates
                detail = f"{node}: provider_request: {safe_diagnostic(error, schema)}{provider_diagnostic(error)}"
                self.logger.warning("%s", detail)
                self.issues.append(detail)
                if isinstance(error, TimeoutError):
                    # Stop this invocation rather than accumulating live requests
                    # when a provider is slow or does not acknowledge cancellation.
                    reason = "provider_request_timeout" if self.remaining_seconds() > 0 else "time_limit"
                    self.retryable_failure = False
                    self.defer_provider_stage(node, reason, error, 0, retry + 1)
                    return None
                from ...benchmark.pacing import daily_quota_exhausted
                if daily_quota_exhausted(error):
                    self.retryable_failure = False
                    self.defer_provider_stage(node, "provider_daily_quota_exhausted", error, retry_delay(error), retry + 1)
                    return None
                self.retryable_failure = transient(error)
                if self.retryable_failure:
                    quota_recovery = provider_status(error) == 429
                    # A hypothetical next sleep cannot exhaust recovery allowance
                    # when no further transient retry is permitted in the first place.
                    if not quota_recovery and retry >= self.config.max_provider_retries:
                        self.defer_provider_stage(node, "provider_recovery_exhausted", error, 0, retry + 1)
                        return None
                    if quota_recovery and (self.calls >= self.call_limit - reserved_calls
                                           or self.tokens + reserve > self.token_limit):
                        # Keep 429 recovery's existing admission/termination policy.
                        continue
                    if not quota_recovery and (self.calls >= self.call_limit - reserved_calls
                                               or self.tokens + reserve > self.token_limit):
                        reason = ("provider_retry_call_limit" if self.calls >= self.call_limit - reserved_calls
                            else "provider_retry_token_limit")
                        self.defer_provider_stage(node, reason, error, 0, retry + 1)
                        return None
                    delay = max(retry_delay(error), min(120, self.provider_pacer.backoff * 2 ** retry))
                    if delay > self.config.provider_max_retry_wait_seconds:
                        self.retryable_failure = False
                        self.defer_provider_stage(node, "provider_retry_wait_limit", error, delay, retry + 1)
                        return None
                    if not quota_recovery and delay >= self.timing.wall_remaining:
                        self.defer_provider_stage(node, "provider_retry_wall_time_limit", error, delay, retry + 1)
                        return None
                    if self.recovery_wait_seconds + delay > self.config.provider_recovery_budget_seconds:
                        self.defer_provider_stage(node, "provider_recovery_budget", error, delay, retry + 1)
                        return None
                    hint = retry_hint(error)
                    source = hint.source if hint is not None else "exponential_backoff"
                    reason = "provider_retry_after" if hint is not None else "provider_backoff"
                    self.logger.warning("%s: provider_recovery_wait seconds=%g source=%s scope=invocation", node, delay, source)

                    async def recover(reason=reason, delay=delay, source=source):
                        with self.timing.quota_wait(reason=reason, seconds=delay, source=source):
                            await getattr(self.provider_pacer, "sleep", asyncio.sleep)(delay)

                    try:
                        # Reserve before sleeping: concurrent siblings keep
                        # their own allowances and no wait holds the pacer lock.
                        self.recovery_wait_seconds += delay
                        await within_deadline(recover(), self.timing)
                    except TimeoutError:
                        self.stop = "time_limit"
                        return None
                    retry += 1
                    continue
                self.stop = "time_limit" if isinstance(error, TimeoutError) else "model_or_schema_error"
                return None
            raw = response.get("raw") if isinstance(response, dict) else response
            usage = getattr(raw, "usage_metadata", None)
            if usage and all(isinstance(usage.get(key), int) and not isinstance(usage[key], bool) and usage[key] >= 0
                             for key in ("input_tokens", "output_tokens")):
                actual_tokens = usage["input_tokens"] + usage["output_tokens"]
                self.tokens += actual_tokens - reserve
                self.estimates -= reserve
                if quota_reservation is not None:
                    self.provider_pacer.settle(quota_reservation, actual_tokens)
                if token_reservation is not None:
                    token_reservation.settle(actual_tokens)
            self.retryable_failure = False
            return response

    def defer_provider_stage(self, node, reason, error, delay, attempts):
        """A provider outage leaves partial work intact; it is not a schema failure."""
        self.stop = reason
        self.deferred_stages.append(DeferredProviderStage(node=node, reason=reason,
            http_status=provider_status(error), retry_after_seconds=retry_delay(error) or None, attempts=attempts))
        self.issues.append(f"{node}: {reason}: http_status={provider_status(error)} "
            f"requested_wait_seconds={delay:g} max_wait_seconds={self.config.provider_max_retry_wait_seconds:g} "
            f"recovery_wait_seconds={self.recovery_wait_seconds:g} "
            f"recovery_budget_seconds={self.config.provider_recovery_budget_seconds:g}. "
            "Etapa pendiente por indisponibilidad del proveedor; evidencias, hipótesis y resultados parciales conservados.")

    async def plan_investigation(self, state):
        plan = await self.call("plan_investigation", state, self.plan_schema)
        if plan:
            try:
                _unique(plan.hypotheses, "hypothesis")
                criteria = {c.id for c in self.request.criteria}
                if any(h.criterion_id is not None and h.criterion_id not in criteria for h in plan.hypotheses):
                    raise ValueError("Unknown hypothesis criterion.")
                # Planning precedes every tool call, so no source excerpt can have been
                # delivered yet. Citations here are only ever invented, and an invented ID
                # is guaranteed to fail as unknown_evidence_ids in the first evaluation.
                delivered = {item.id for item in self.references()}
                invented = sum(1 for h in plan.hypotheses for i in h.evidence_ids if i not in delivered)
                if invented:
                    self.issues.append(f"plan_investigation: discarded {invented} hypothesis citations "
                        "that are not delivered evidence.")
                    plan = plan.model_copy(update={"hypotheses": [
                        h.model_copy(update={"evidence_ids": [i for i in h.evidence_ids if i in delivered]})
                        for h in plan.hypotheses]})
            except ValueError as error:
                self.issues.append(str(error))
                self.stop = "invalid_plan"
                plan = None
        update = {"plan": plan, "hypotheses": plan.hypotheses if plan else [], "model_calls": self.calls}
        if plan is None:
            update.update(termination_reason=self.stop or "invalid_plan", missing_information=[
                "A valid investigation plan could not be produced; investigation, evidence evaluation and critical review were not started."])
        return update

    def route_plan(self, state):
        return "investigate" if state["plan"] is not None and not self.stop else "finalize"

    async def investigate(self, state):
        # Leave an evaluation and a correctable critical review available.
        if self.calls >= self.call_limit - self.closing_call_reserve or self.tools.budget_usage.tool_calls >= self.tool_limit:
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
            gaps = self.evaluation_evidence_gaps(evaluation)
            if gaps:
                evaluation = evaluation.model_copy(update={
                    "sufficient": False,
                    "missing_information": list(dict.fromkeys([*evaluation.missing_information, *gaps])),
                })
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
        reason = self.stop or ("provenance_unverifiable" if self.provenance_blocked else "")
        if not reason:
            if evaluation and evaluation.sufficient and not evaluation.missing_information:
                reason = "sufficient_evidence"
            elif state["iterations"] >= self.config.max_iterations:
                reason = "iteration_limit"
            elif self.tools.budget_usage.tool_calls >= self.tool_limit:
                reason = "tool_call_limit"
            elif self.calls >= self.call_limit - self.closing_call_reserve:
                reason = "model_call_limit"
            elif self.remaining_seconds() <= 0:
                reason = "time_limit"
        return "review_findings" if reason else "investigate"

    def review_termination_reason(self, state):
        reason = self.stop or ("provenance_unverifiable" if self.provenance_blocked else "")
        if not reason:
            evaluation = state["evaluation"]
            reason = ("sufficient_evidence" if evaluation and evaluation.sufficient and not evaluation.missing_information
                      else "iteration_limit" if state["iterations"] >= self.config.max_iterations
                      else "tool_call_limit" if self.tools.budget_usage.tool_calls >= self.tool_limit
                       else "model_call_limit")
        return reason

    async def review_findings(self, state):
        reason = self.review_termination_reason(state)
        # Budget termination can still leave room for review; provider/schema failures do not.
        closing_stop = self.stop if self.can_review_stopped(state) else ""
        if closing_stop:
            self.stop = ""
        try:
            review = await self.call("review_findings", state, self.review_schema)
        finally:
            if closing_stop:
                self.stop = closing_stop
        return {"review": review, "termination_reason": self.stop or reason, "model_calls": self.calls}

    def can_review_stopped(self, state):
        return state["evaluation"] is not None and self.stop in {
            "model_call_limit", "tool_call_limit", "no_investigation_progress",
        }

    def verify_references(self, evidence):
        """Resolve commit attribution once per cited file, shared by specialized results."""
        snapshot = self.tools.accessible_snapshot
        source_files = {s.id: s for s in snapshot.files}
        for reference in evidence:
            if snapshot.repository.commit and reference.file_id not in self._commit_checks:
                self._commit_checks[reference.file_id] = verify_commit(
                    snapshot.repository, source_files[reference.file_id], self.remaining_seconds(),
                )
        mismatch = any(r.file_id in self._commit_checks and not self._commit_checks[r.file_id].matched for r in evidence)
        verified = [self.attributed_reference(r) for r in evidence]
        return verified, mismatch

    def attributed_reference(self, reference):
        check = getattr(self, "_commit_checks", {}).get(reference.file_id)
        if check is None:
            return reference
        return reference.model_copy(update={
            "commit": self.tools.accessible_snapshot.repository.commit if check.matched else None,
            "commit_verification": ("exact" if check.reason == "verified" else "line_endings_equivalent") if check.matched else "unverified",
            "git_blob_id": check.blob_id,
        })

    def evidence_issues(self, ids, references):
        """Common preflight and final checks share the same evidence requirements."""
        issues = []
        evidence = [references[i] for i in dict.fromkeys(ids) if i in references]
        if set(ids) - references.keys():
            issues.append("unknown_evidence_ids")
        if not any(record.kind == "source" for record in evidence):
            issues.append("source_not_inspected")
        evidence, mismatch = self.verify_references(evidence)
        if mismatch:
            issues.extend(sorted({self._commit_checks[r.file_id].reason for r in evidence
                if r.file_id in self._commit_checks and not self._commit_checks[r.file_id].matched}))
        return evidence, list(dict.fromkeys(issues))

    def evaluation_evidence_gaps(self, evaluation):
        references = {r.id: r for r in self.references()}
        gaps = []
        self.evidence_recovery_tasks = []
        provenance_failures, actionable = False, False
        for candidate in evaluation.candidates:
            evidence, issues = self.evidence_issues(candidate.evidence_ids, references)
            if issues:
                provenance_failures |= any(r.file_id in self._commit_checks and not self._commit_checks[r.file_id].matched for r in evidence)
                actionable |= bool(set(issues) & {"source_not_inspected", "unknown_evidence_ids"})
                instruction = self.evidence_recovery_instruction("candidate", candidate.id, issues, evidence, references,
                    question=candidate.description, evidence_needed=candidate.components)
                gaps.append(f"Candidate {candidate.id}: {', '.join(issues)}. {instruction}")
        for hypothesis in evaluation.hypotheses:
            issues = []
            if hypothesis.evidence_ids:
                evidence, issues = self.evidence_issues(hypothesis.evidence_ids, references)
                provenance_failures |= any(r.file_id in self._commit_checks and not self._commit_checks[r.file_id].matched for r in evidence)
                actionable |= bool(set(issues) & {"source_not_inspected", "unknown_evidence_ids"})
            if issues:
                instruction = self.evidence_recovery_instruction("hypothesis", hypothesis.id, issues, evidence, references,
                    question=hypothesis.question, evidence_needed=hypothesis.evidence_needed)
                gaps.append(f"Hypothesis {hypothesis.id}: {', '.join(issues)}. {instruction}")
            elif hypothesis.status in {"pending", "inconclusive"}:
                actionable = True
                self.evidence_recovery_instruction("hypothesis", hypothesis.id, [], [], references,
                    question=hypothesis.question, evidence_needed=hypothesis.evidence_needed)
                gaps.append(f"Resolve hypothesis {hypothesis.id} with source evidence or explain its concrete blocker: {hypothesis.question}")
        actionable |= bool(evaluation.missing_information)
        self.provenance_blocked = provenance_failures and not actionable
        return gaps

    def evidence_recovery_instruction(self, subject_type, identifier, issues, evidence, references, *, question, evidence_needed):
        repairable = not issues or bool(set(issues) & {"source_not_inspected", "unknown_evidence_ids"})
        cited_paths = list(dict.fromkeys(record.path for record in evidence))
        existing_source = [record for record in references.values() if record.kind == "source" and record.path in cited_paths
            and (record.file_id not in self._commit_checks or self._commit_checks[record.file_id].matched)]
        inspected = {record.path for record in existing_source}
        self.evidence_recovery_tasks.append({
            "subject_type": subject_type, "id": identifier, "question": question,
            "issues": issues, "evidence_needed": evidence_needed, "cited_paths": cited_paths,
            "paths_to_inspect": [path for path in cited_paths if path not in inspected] if repairable else [],
            "available_source_evidence_ids": [record.id for record in existing_source] if repairable else [],
            "action": "inspect_source_or_correct_citations" if repairable else "report_provenance_blocker",
        })
        if repairable:
            paths = ", ".join(cited_paths) or "the files required by this question"
            return (f"Inspect relevant source and callers with get_source_excerpt for {paths}, or correct evidence_ids "
                "using already delivered source excerpts. Metadata and relationship hints alone do not establish behavior. "
                "Use this question's evidence_needed to select the next read; do not repeat satisfied reads or unrelated discovery.")
        return "Snapshot provenance cannot be repaired by re-reading the same files. Retain the snapshot evidence and report the attribution blocker."

    def finalize(self, state):
        references = {r.id: r for r in self.references()}
        # The retained ledger is verified like any cited evidence: a read that no finding
        # happens to cite must not claim weaker provenance than one that does.
        ledger, _ = self.verify_references(list(references.values()))
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
            evidence, issues = self.evidence_issues(candidate.evidence_ids, references)
            if criterion is None:
                issues.append("unknown_criterion")
            elif candidate.kind == "violation" and criterion.origin != "explicit":
                issues.append("violation_requires_explicit_criterion")
            if issues:
                limitations.append(f"Candidate {candidate.id}: evidence validation failed ({', '.join(issues)}).")
                review = review.model_copy(update={"status": "insufficient_evidence", "confidence": 0,
                    "rationale": "Host validation failed: " + ", ".join(issues) + "."})
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
        hypotheses = []
        invalid_criteria = {f.criterion_id for f in findings if f.validation_status == "insufficient_evidence"}
        missing_information = list(state["missing_information"])
        for hypothesis in state["hypotheses"]:
            blockers = []
            if hypothesis.status == "pending":
                blockers.append("Investigation ended before this hypothesis was resolved")
            elif hypothesis.status in {"confirmed", "discarded"}:
                if hypothesis.evidence_ids:
                    _, issues = self.evidence_issues(hypothesis.evidence_ids, references)
                    blockers.extend(issues)
                elif hypothesis.criterion_id in invalid_criteria:
                    blockers.append("Related candidates failed evidence validation and this hypothesis has no independent source citations")
            if blockers:
                reason = "; ".join(blockers)
                hypothesis = hypothesis.model_copy(update={"status": "inconclusive",
                    "rationale": f"{hypothesis.rationale}\nHost validation: {reason}.".strip()})
                missing_information.append(f"Hypothesis {hypothesis.id}: {reason}.")
            hypothesis = hypothesis.model_copy(update={
                "evidence_ids": [identifier for identifier in hypothesis.evidence_ids if identifier in references],
            })
            hypotheses.append(hypothesis)
        if any(h.status == "inconclusive" for h in hypotheses):
            limitations.append("Some hypotheses remain inconclusive; absence of findings does not establish boundary compliance.")
        if state["plan"] is None and state["iterations"] == 0:
            limitations.append("Investigation, evidence evaluation and critical review were not started because no valid plan was available.")
        elif not state["review"]:
            limitations.append("Critical review was not completed; no candidate is accepted.")
        termination_reason = state["termination_reason"]
        if termination_reason == "sufficient_evidence" and (
            any(f.validation_status == "insufficient_evidence" for f in findings)
            or any(h.status == "inconclusive" for h in hypotheses)
            or missing_information
        ):
            termination_reason = "evidence_validation_failed"
            limitations.append("Model-declared sufficiency was not upheld by final evidence validation.")
        result = self.result_schema(
            repository_id=state["repository_id"], commit=state["commit"],
            snapshot_hash=self.tools.context.input.snapshot_hash, objective=state["objective"],
            plan=state["plan"], findings=findings, hypotheses=hypotheses,
            missing_information=list(dict.fromkeys(missing_information)), limitations=list(dict.fromkeys(limitations)),
            termination_reason=termination_reason, deferred_stages=self.deferred_stages, model_calls=self.calls,
            tool_calls=self.tools.budget_usage.tool_calls, iterations=state["iterations"],
            accounted_tokens=self.tokens, estimated_tokens=self.estimates,
            evidence=ledger,
        )
        return {"result": result}

    def route_review(self, state):
        return "finalize"

    def _build_graph(self):
        graph = StateGraph(InvestigationState)
        for name in ("plan_investigation", "investigate", "evaluate_evidence", "review_findings", "finalize"):
            graph.add_node(name, getattr(self, name))
        graph.add_node("tools", ToolNode(self.native_tools, handle_tool_errors=True))
        graph.add_edge(START, "plan_investigation")
        graph.add_conditional_edges("plan_investigation", self.route_plan, ["investigate", "finalize"])
        graph.add_conditional_edges("investigate", self.route_investigation,
                                   ["tools", "evaluate_evidence", "review_findings"])
        graph.add_edge("tools", "investigate")
        graph.add_conditional_edges("evaluate_evidence", self.is_sufficient,
                                   ["investigate", "review_findings"])
        graph.add_conditional_edges("review_findings", self.route_review, ["investigate", "review_findings", "finalize"])
        graph.add_edge("finalize", END)
        return graph.compile()
