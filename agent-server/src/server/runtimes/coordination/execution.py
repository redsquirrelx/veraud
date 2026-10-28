"""Read-only hierarchical coordination with bounded conditional refinement."""

import asyncio
from abc import ABC, abstractmethod
from time import monotonic
from types import SimpleNamespace
from typing import TYPE_CHECKING, ClassVar
from uuid import uuid4

from langchain_core.language_models.chat_models import BaseChatModel

from server.infrastructure.llm.retry import RequestPacer
from server.infrastructure.tracing import LangSmithTracingBackend

from ...blackboard.publication import publication_for
from ...config.token_budget import effective_token_budget_policy, token_budget_exceeded
from ..investigation.agent import InvestigationExecution
from ..investigation.provider import lean_schema, model_pacer
from ..invocation_reporting import observe_invocation
from ..repository.context import RepositoryContext
from ..repository.schemas import ExecutionBudget
from ..repository.timing import ActiveDeadline, within_deadline
from ..repository.tools import RepositoryToolset
from .knowledge import (
    commitment_resolved,
    covered,
    new_source,
    project,
    task_specs,
    validation_progress,
)
from .schemas import Consumption
from .synthesis import (
    evidence_index,
    follow_up_key,
    stable_id,
    terminal_collection_blocker,
    terminal_provider_blocker,
)

if TYPE_CHECKING:
    from ...blackboard.identity import AuditIdentity
    from ...blackboard.interface import Blackboard


class CoordinatorSynthesisExecution(InvestigationExecution):

    def _context(self, state):
        return state["compact_context"]

    def structured_schema(self, schema):
        # Bound-heavy nested JSON schemas can exceed Gemini's generation-state limit.
        # Preserve the full Pydantic contract for local validation after generation.
        return lean_schema(schema) if isinstance(self.model, BaseChatModel) else schema

    def prepare_structured_input(self, node, value):
        if not isinstance(value, dict) or not isinstance(value.get("groups"), list):
            return value
        # An empty group asserts no finding. Omit it instead of spending a full
        # correction attempt on minItems; never populate it with invented IDs.
        groups = value["groups"]
        kept = [group for group in groups if not isinstance(group, dict) or group.get("finding_refs") != []]
        if len(kept) != len(groups):
            self.issues.append(f"{node}: omitted {len(groups) - len(kept)} empty finding groups; no findings inferred.")
        return {**value, "groups": kept}

    def structured_correction_context(self, node, state):
        context = state.get("compact_context", {})
        return {"allowed_finding_refs": list(context.get("findings", {})),
            "allowed_evidence_refs": list(context.get("evidence", {})),
            "empty_result": "Use groups=[] when no supported groups exist. Each group must cite real finding_refs."}


class CoordinatorAgent:
    """Shared lifecycle; subclasses supply config, graph, contracts and prompts."""

    def __init__(self, model, config=None, *, tracing_backend=None, investigator_factory=None, provider_pacer=None,
                 blackboard: "Blackboard | None" = None, audit_identity: "AuditIdentity | None" = None):
        self.model = getattr(model, "llm", model)
        self.agent_models = {}
        self.agent_output_limits = {}
        self.config = config or self.config_type()
        if set(self.config.prompts) - set(self.config.prompt_nodes):
            raise ValueError("Coordinator prompt overrides must name configured cognitive nodes.")
        self.tracing = tracing_backend or LangSmithTracingBackend()
        self.factory = investigator_factory
        self.provider_pacer = provider_pacer
        self.blackboard = blackboard
        self.audit_identity = audit_identity

    @classmethod
    def continuation_actionable(cls, result, gap):
        if cls.actionable_gap(gap, result.invocations):
            return True
        # A fresh manager-reserved attempt may recover an essential execution
        # failure; terminal contracts/quotas and unchanged bound repairs cannot.
        calls = [r for r in result.invocations if r.assignment.investigator_id == gap.investigator_id]
        return bool(gap.kind == "essential_failure" and not gap.commitments and calls
            and not terminal_provider_blocker(calls[-1].result) and not terminal_collection_blocker(calls[-1]))

class CoordinatorExecution(ABC):
    """Shared dispatch, reservations, provenance, collection and synthesis.

    Concrete coordinators bind their own registry, contracts, policies and graph.
    No audit dimension is imported or selected by this runtime.
    """

    analysis_fields: ClassVar[dict[str, tuple[str, ...]]] = {}
    binding_fields: ClassVar[dict[str, tuple[str, ...]]] = {}
    source_issue_tokens = ("source_not_inspected",)

    @abstractmethod
    def build_graph(self):
        """Bind the concrete coordinator's topology and output contract."""

    def __init__(self, agent, tools, request):
        self.agent, self.tools, self.request = agent, tools, request
        selected = getattr(request, "investigator_ids", None)
        if selected is not None:
            if set(selected) - self.registry.keys():
                raise ValueError("Unknown investigator selection.")
            self.registry = {key: spec for key, spec in self.registry.items() if key in selected}
        self.blackboard = getattr(agent, "blackboard", None)
        self.publication = publication_for(agent) if self.blackboard is not None else None
        self.audit_identity = self.publication.identity if self.publication is not None else getattr(agent, "audit_identity", None)
        self.trace_name = getattr(agent, "trace_name", "coordinator")
        self.config = agent.config
        self.started = monotonic()
        self.transitions = []
        self.spent = Consumption()
        continuation = getattr(agent, "continuation", None)
        self.baseline = continuation.assessment if continuation is not None else None
        self.continuation_gap_ids = set(continuation.gap_ids) if continuation is not None else set()
        self.baseline_count = len(self.baseline.invocations) if self.baseline is not None else 0
        self.round_limit = self.config.max_rounds + (self.baseline.rounds_completed if self.baseline is not None else 0)
        if self.baseline is not None:
            snapshot = tools.accessible_snapshot
            if (self.baseline.repository_id != snapshot.repository.name or self.baseline.snapshot_hash != snapshot.repository.snapshot_hash
                    or self.baseline.commit != snapshot.repository.commit or self.baseline.targets != request.targets):
                raise ValueError("Continuation baseline does not match repository revision/scope.")
            if self.publication is not None and continuation.publication is not None:
                self.publication.reuse_children(continuation.publication,
                    [r.assignment.invocation_id for r in self.baseline.invocations])
        self.global_budget = tools.context.input.budget
        if tools.timing is None:
            tools.timing = ActiveDeadline(self.config.timeout_seconds,
                wall_deadline=tools.context.started_at + min(self.global_budget.max_elapsed_seconds, self.config.max_wall_time_seconds),
                cancellation_grace_seconds=self.config.cancellation_grace_seconds)
        self.timing = tools.timing
        self.token_budget = tools.token_budget
        self.invocation_tokens = {}
        self._collected_records = {}
        self.synth = self.synthesis_execution_type(agent.model, self.config, tools, request)
        self.synth.blackboard = self.blackboard
        self.synth.audit_identity = self.audit_identity
        self.provider_pacer = model_pacer(agent.model, injected=getattr(agent, "provider_pacer", None),
            rate_limits=self.config.provider_rate_limits,
            interval=max(self.config.provider_request_interval_seconds,
            self.config.invocation_limits.provider_request_interval_seconds),
            max_retries=self.config.max_provider_retries,
            backoff=max(self.config.provider_retry_backoff_seconds,
                self.config.invocation_limits.provider_retry_backoff_seconds))
        self.synth.provider_pacer = self.provider_pacer
        self.investigation_start_pacer = RequestPacer(interval=self.config.investigation_start_interval_seconds)
        self.graph = self.build_graph()
        paths = [f.path for f in tools.accessible_snapshot.files]
        self.paths = set(paths)
        for target in request.targets:
            if target not in paths and not any(p.startswith(target.rstrip("/") + "/") for p in paths):
                raise ValueError(f"Target is not accessible in the snapshot: {target}")

    def tick(self, name):
        self.transitions.append(name)
        self.timing.touch()
        self.synth.logger.info("%s node=%s", self.trace_name, name)

    def assessment_identity(self):
        if self.publication is None:
            return uuid4().hex
        if getattr(self.agent, "_blackboard_publication", None) is not None:
            return self.publication.invocation_id
        return self.publication.run_id

    def remaining(self):
        return self.timing.remaining

    def resume_synthesis(self):
        if self.synth.retryable_failure:
            # A later evidence round may recover from a transient outage. Keep
            # all accounting/deadlines; never clear permanent request failures.
            self.synth.stop = ""
            self.synth.retryable_failure = False

    def resources(self):
        return {
            "calls": min(self.config.max_model_calls, self.global_budget.max_model_calls) - self.spent.model_calls,
            "tokens": (self.token_budget.remaining if self.token_budget is not None else
                       min(self.config.max_total_tokens, self.global_budget.max_total_tokens,
                           self.global_budget.max_tokens_per_objective) - self.spent.accounted_tokens),
            "tools": min(self.config.max_tool_calls, self.global_budget.max_tool_calls) - self.spent.tool_calls,
        }

    def can_dispatch(self, records):
        remaining = self.resources()
        # Reserve the whole per-invocation envelope before dispatch, not after parallel calls.
        limits = self.config.invocation_limits
        return (len(records) - self.baseline_count < self.config.max_invocations and self.remaining() > 0
                and remaining["calls"] >= limits.max_model_calls
                and not token_budget_exceeded(1 if self.token_budget is not None else limits.max_total_tokens, remaining["tokens"])
                and remaining["tools"] >= limits.max_tool_calls)

    def initial_state(self):
        state = {"assessment_id": self.assessment_identity(), "repository_id": self.tools.accessible_snapshot.repository.name,
            "snapshot_hash": self.tools.context.input.snapshot_hash, "scope": self.request.targets,
            "investigator_registry": [s.capability for s in self.registry.values()], "rounds_completed": 0,
            "max_rounds": self.round_limit, "budgets": {}, "pending_assignments": [], "completed_assignments": [],
            "invocation_status": {}, "investigation_results": [], "execution_records": [], "collected_count": 0,
            "initial_plan": [], "consolidated_findings": [], "material_gaps": [], "actionable_followups": [],
            "resolved_gap_ids": [], "withdrawn_finding_refs": [], "summary": "", "messages": [], "termination_reason": ""}
        if self.baseline is not None:
            state.update(investigation_results=list(self.baseline.invocations), initial_plan=list(self.baseline.initial_plan),
                rounds_completed=self.baseline.rounds_completed, material_gaps=list(self.baseline.material_gaps),
                consolidated_findings=list(self.baseline.consolidated_findings), resolved_gap_ids=list(self.baseline.resolved_gap_ids),
                withdrawn_finding_refs=list(self.baseline.withdrawn_finding_refs))
        return state

    @property
    def reported_consumption(self):
        if self.baseline is None:
            return self.spent
        previous = self.baseline.consumption
        return Consumption(**{key: getattr(previous, key) + getattr(self.spent, key)
            for key in ("model_calls", "tool_calls", "accounted_tokens", "estimated_tokens")},
            model_calls_estimated=previous.model_calls_estimated or self.spent.model_calls_estimated)

    def assignment(self, investigator, question, round_number, targets, refs=None, gaps=None):
        return self.assignment_type(invocation_id=uuid4().hex, investigator_id=investigator, round=round_number,
                          question=question, targets=targets, evidence_refs=refs or [], gap_ids=gaps or [])

    def plan_assessment(self, state):
        self.tick("plan_assessment")
        if self.baseline is not None:
            grouped = {}
            for gap in self.baseline.material_gaps:
                if gap.id in self.continuation_gap_ids and self.agent.continuation_actionable(self.baseline, gap):
                    grouped.setdefault(follow_up_key(gap), []).append(gap)
            plan = [self.follow_up_assignment(group, state["rounds_completed"] + 1) for group in grouped.values()]
            return {"pending_assignments": plan, "initial_plan": list(self.baseline.initial_plan)}
        plan = [self.assignment(key, self.request.objective + "\n" + spec.capability.capability,
                               1, self.request.targets) for key, spec in self.registry.items()]
        return {"pending_assignments": plan, "initial_plan": plan}

    def project_record(self, record):
        projection = project(record, self.analysis_fields.get(record.assignment.investigator_id, ()),
            self.binding_fields.get(record.assignment.investigator_id, ()))
        if record.result is not None:
            snapshot = self.tools.accessible_snapshot
            ranges = {s.id: (s.file_id, s.start_line, s.end_line) for s in snapshot.symbols}
            ranges.update({f.id: (f.id, 1, f.line_count) for f in snapshot.files})
            projection["source_inspected_subject_ids"] = sorted({i for c in projection["commitments"] for i in c["subject_ids"]
                if i in ranges and covered(record.evidence, *ranges[i])})
        return projection

    def follow_up_assignment(self, gaps, round_number):
        first = gaps[0]
        commitments = {item.model_dump_json(): item for gap in gaps for item in gap.commitments}
        assignment = self.assignment(first.investigator_id, first.question, round_number, first.targets,
            list(dict.fromkeys(ref for gap in gaps for ref in gap.evidence_refs))[:8], [gap.id for gap in gaps])
        return assignment.model_copy(update={"commitments": list(commitments.values())[:40],
            "diagnostics": list(dict.fromkeys(text for gap in gaps for text in gap.diagnostics))})

    def task_question(self, commitment, task):
        prefix = ("Obtain unavailable external context for " if task == "external_context" else
            "Complete source inspection for " if task in {"source_inspection", "deferred_work"}
            else "Repair and independently review the assessment of ")
        return prefix + ", ".join(commitment.subject_ids) + ". Original question: " + commitment.question

    async def delegate_investigations(self, state):
        from ...services.execution_failures import (
            ExecutionFailure,
            ResourceShortfall,
            failure_from_exception,
        )

        self.tick("delegate_investigations")
        semaphore = asyncio.Semaphore(self.config.max_parallel)
        reserved = dict(self.resources())
        existing = len(state["investigation_results"]) - self.baseline_count
        limits = self.config.invocation_limits
        dispatch = []
        failures = {}
        for assignment in state["pending_assignments"]:
            requirements = [("invocations", self.config.max_invocations - existing - len(dispatch), 1),
                ("seconds", self.remaining(), 0.001), ("calls", reserved["calls"], limits.max_model_calls),
                ("tokens", reserved["tokens"], 1 if self.token_budget is not None else limits.max_total_tokens),
                ("tools", reserved["tools"], limits.max_tool_calls)]
            shortfalls = [ResourceShortfall(resource=key, available=max(0, available), required=required)
                for key, available, required in requirements if available < required
                and (key != "tokens" or token_budget_exceeded(required, available))]
            if shortfalls:
                failures[assignment.invocation_id] = ExecutionFailure(code="execution_budget_exhausted",
                    stage="reserve_invocation", summary="No ejecutado: no se pudo reservar el presupuesto de la investigación.",
                    resources=shortfalls)
                dispatch.append((assignment, None))
                continue
            budget = ExecutionBudget(
                max_model_calls=limits.max_model_calls,
                max_total_tokens=self.token_budget.limit if self.token_budget is not None else limits.max_total_tokens,
                max_tokens_per_objective=self.token_budget.limit if self.token_budget is not None else limits.max_total_tokens,
                max_tool_calls=max(1, limits.max_tool_calls),
                max_input_tokens_per_call=min(self.global_budget.max_input_tokens_per_call, limits.max_context_characters // 2),
                # Carry the execution envelope through supervisors; their own
                # output setting must not become a cap on a child's override.
                max_output_tokens_per_call=self.global_budget.max_output_tokens_per_call,
                max_retrieved_characters=self.global_budget.max_retrieved_characters,
                max_elapsed_seconds=min(self.timing.wall_remaining, self.global_budget.max_elapsed_seconds),
            )
            reserved["calls"] -= limits.max_model_calls
            if self.token_budget is None:
                reserved["tokens"] -= limits.max_total_tokens
            reserved["tools"] -= limits.max_tool_calls
            dispatch.append((assignment.model_copy(update={"budget": budget}), budget))

        async def invoke(assignment, budget):
            if budget is None:
                return self.raw_invocation_type(assignment=assignment, status="skipped", error="execution_budget_exhausted",
                    failure=failures[assignment.invocation_id])
            async with semaphore:
                started = monotonic()
                try:
                    async def wait_for_start():
                        async with self.investigation_start_pacer.lock:
                            await self.investigation_start_pacer.wait()
                            self.investigation_start_pacer.completed_attempt()
                    await within_deadline(wait_for_start(), self.timing)
                except TimeoutError:
                    # No investigator was started: do not charge its reserved envelope.
                    return self.raw_invocation_type(assignment=assignment.model_copy(update={"budget": None}),
                        status="skipped", error="assessment_time_exhausted", duration_seconds=monotonic() - started)
                child = None
                timing = None
                try:
                    if self.remaining() <= 0:
                        raise TimeoutError
                    spec = self.registry[assignment.investigator_id]
                    timing = self.timing.fork(limits.timeout_seconds,
                        label=assignment.investigator_id, invocation_id=assignment.invocation_id,
                        max_wall_time_seconds=limits.max_wall_time_seconds, cancellation_grace_seconds=limits.cancellation_grace_seconds)
                    token_scope = self.token_budget.fork() if self.token_budget is not None else None
                    if token_scope is not None:
                        self.invocation_tokens[assignment.invocation_id] = token_scope
                    child = RepositoryToolset(RepositoryContext(self.tools.context.snapshot,
                        self.tools.context.input.model_copy(update={"budget": budget})),
                        workspace_root=self.tools.policy.workspace_root, limits=self.tools.limits,
                        token_budget=token_scope, timing=timing, retrieval_budget=self.tools.retrieval_budget)
                    config = self.invocation_config(spec, limits)
                    output_overrides = getattr(self.agent, "agent_output_limits", {})
                    if assignment.investigator_id in output_overrides:
                        config = type(config).model_validate({**config.model_dump(),
                            "max_output_tokens": output_overrides[assignment.investigator_id]})
                    agent_models = getattr(self.agent, "agent_models", {})
                    selected_model = agent_models.get(assignment.investigator_id, self.agent.model)
                    investigator = (self.agent.factory(assignment.investigator_id, selected_model, config)
                                    if self.agent.factory else spec.agent_class(selected_model, config,
                                        provider_pacer=self.provider_pacer))
                    investigator.agent_models = agent_models
                    investigator.agent_output_limits = output_overrides
                    # Factory-created children share the same dependency as default agents.
                    investigator.blackboard = self.blackboard
                    if self.publication is not None:
                        investigator._blackboard_publication = self.publication.child(
                            assignment.invocation_id, assignment.investigator_id,
                        )
                    self.configure_invocation(investigator, assignment, state)
                    index = self.prior_evidence_index(state["investigation_results"])
                    context = self.request.architectural_context + "\nScoped targets: " + ", ".join(assignment.targets)
                    context += "\nPrior evidence references (navigation only; retrieve and verify): " + str([
                        index[ref].model_dump() for ref in assignment.evidence_refs[:8] if ref in index])
                    value = await observe_invocation(within_deadline(within_deadline(self.agent.tracing.wrap_stage(
                        investigator.run(child, self.investigator_request(spec, assignment, context)),
                        **self.invocation_metadata(assignment, state)), timing), self.timing),
                        agent_id=assignment.investigator_id, invocation_id=assignment.invocation_id,
                        run_id=self.audit_identity.run_id if self.audit_identity else "unscoped")
                    return self.raw_invocation_type(assignment=assignment, status="received", value=value,
                        evidence=self.invocation_evidence(value, child),
                        duration_seconds=monotonic() - started)
                except Exception as error:  # noqa: BLE001 - investigator boundary; cancellation propagates
                    return self.raw_invocation_type(assignment=assignment, status="timeout" if isinstance(error, TimeoutError) else "failed",
                        error=type(error).__name__, duration_seconds=monotonic() - started,
                        failure=failure_from_exception(error, "invoke_child"),
                        evidence=self.references(child) if child else [])
                finally:
                    if timing is not None:
                        timing.close()

        tasks = [asyncio.create_task(invoke(a, b)) for a, b in dispatch]
        received = {}
        try:
            for completed in asyncio.as_completed(tasks):
                raw = await completed
                received[raw.assignment.invocation_id] = raw
                self.collect_received(raw, state)
        finally:
            from ..repository.timing import cancel_bounded
            await asyncio.gather(*(cancel_bounded(task, self.config.cancellation_grace_seconds)
                for task in tasks if not task.done()))
        return {"execution_records": [received[a.invocation_id] for a, _ in dispatch], "pending_assignments": []}

    def collect_received(self, raw, state):
        """Validate, account and publish each completed child before slower siblings."""
        update = self.collect_findings(dict(state, execution_records=[raw]), incremental=True)
        record = next(r for r in update["investigation_results"] if r.assignment.invocation_id == raw.assignment.invocation_id)
        self.publish_collected(record)

    def publish_collected(self, record):
        from ...services.execution_failures import (
            ExecutionValidationError,
            failure_from_exception,
        )

        if self.publication is None or not self.timing.publication_allowed or record.result is None:
            return
        child = self.publication.child(record.assignment.invocation_id, record.assignment.investigator_id)
        # Native children already published their original output and tool measurements.
        # Supervisor copies may be reviewed/enriched and must never replace that output.
        if child.result is not None:
            return
        try:
            self.publish_received_result(child, record)
        except ExecutionValidationError as error:
            # Keep sibling investigations running and retain already-accounted usage.
            # A publication conflict cannot supply claims or justify reinvestigation.
            failure = failure_from_exception(error, "publish_result")
            updates = {"status": "failed", "result": None, "error": failure.exception_type, "failure": failure}
            if "evidence_sufficient" in type(record).model_fields:
                updates.update(evidence_sufficient=False, coverage_issues=[*record.coverage_issues, failure.summary])
            self._collected_records[record.assignment.invocation_id] = record.model_copy(update=updates)

    def publish_received_result(self, child, record):
        child.publish_investigation(record.result, record.evidence)

    @staticmethod
    def references(tools):
        # Reuse the investigators' provenance adapter, including metadata and line ranges.
        return InvestigationExecution.references(SimpleNamespace(tools=tools, _commit_checks=tools.commit_verifications))

    async def run(self, *, recursion_limit: int):
        """Execute the domain graph once, then publish its structured result in Python."""
        state = await self.graph.ainvoke(self.initial_state(), {"recursion_limit": recursion_limit})
        result = state["result"]
        if self.publication is not None and self.timing.publication_allowed:
            self.publication.publish_assessment(result)
        return result

    def investigator_request(self, spec, assignment, context):
        args = {"objective": assignment.question, "architectural_context": context, "follow_up": assignment.commitments,
            "follow_up_diagnostics": assignment.diagnostics}
        if self.request.criteria:
            args["criteria"] = self.request.criteria
        return spec.request_class(**args)

    def configure_investigator(self, investigator):
        """Optional sibling-coordinator runtime binding hook."""

    def configure_invocation(self, investigator, assignment, state):
        self.configure_investigator(investigator)

    def invocation_config(self, spec, limits):
        return spec.agent_class.config_type.model_validate(limits.model_dump())

    def invocation_evidence(self, value, child):
        return self.references(child)

    def prior_evidence_index(self, records):
        return evidence_index(records)

    def invocation_metadata(self, assignment, state):
        return {"name": self.trace_name + "-investigation", "invocation_id": assignment.invocation_id,
                "investigator_id": assignment.investigator_id, "round": assignment.round,
                "snapshot_hash": state["snapshot_hash"]}

    def validate_collected_result(self, result, raw, state):
        from ...services.execution_failures import ExecutionValidationError
        snapshot = self.tools.accessible_snapshot
        if (result.snapshot_hash != state["snapshot_hash"] or result.commit != snapshot.repository.commit
                or result.repository_id != snapshot.repository.name or result.objective != raw.assignment.question):
            raise ExecutionValidationError("repository_provenance_mismatch", "El resultado no coincide con el repositorio, revisión u objetivo asignado.")
        files = {f.id: f for f in snapshot.files}
        for finding in result.findings:
            for ref in finding.evidence:
                if (ref.snapshot_hash != state["snapshot_hash"] or ref.commit != result.commit
                        or ref.file_id not in files or files[ref.file_id].path != ref.path
                        or files[ref.file_id].content_hash != ref.content_hash):
                    raise ExecutionValidationError("evidence_provenance_mismatch", "La evidencia no corresponde a los archivos y revisión del snapshot.")

    def result_status(self, result):
        if getattr(result, "status", "completed") == "failed":
            return "failed"
        if getattr(result, "status", "completed") != "completed" or getattr(result, "tool_failures", []):
            return "partial"
        if getattr(result, "evaluation_evidence_status", None) == "stale" or getattr(result, "pending_evaluation_evidence_ids", []):
            return "partial"
        coverage = getattr(result, "coverage", None)
        if coverage and any(getattr(coverage, key, []) for key in ("unassessed_candidates", "unassessed_groups", "unassessed_components")):
            return "partial"
        analyses = [a for fields in self.analysis_fields.values() for field in fields for a in getattr(result, field, [])]
        if any(getattr(a, "validation_status", None) != "source_backed" or getattr(a, "validation_issues", [])
                or getattr(a, "conclusion", getattr(a, "cohesion", None)) in {"unknown", "inconclusive"} for a in analyses):
            return "partial"
        return "completed" if (result.termination_reason == "sufficient_evidence" and result.plan
            and not result.missing_information and not any(h.status in {"pending", "inconclusive"} for h in result.hypotheses)
            and not getattr(result, "inconclusive_investigations", [])
            and not any(f.validation_status == "insufficient_evidence" for f in result.findings)) else "partial"

    def synthesis_context(self, context, state, records):
        return context

    def fallback_consumption(self, assignment):
        if assignment.budget is None:
            return Consumption()
        budget = assignment.budget
        scope = self.invocation_tokens.get(assignment.invocation_id)
        return Consumption(model_calls=budget.max_model_calls, tool_calls=budget.max_tool_calls,
            accounted_tokens=(scope.used if scope is not None else 0) if self.token_budget is not None else budget.max_total_tokens,
            estimated_tokens=(scope.estimated if scope is not None else 0) if self.token_budget is not None else budget.max_total_tokens,
            model_calls_estimated=True)

    def synthesis_token_limit(self, remaining):
        if self.token_budget is not None:
            # Descendants count against the shared audit ledger, not this agent's
            # personal allowance. The synthesis engine owns its own call counter.
            return self.config.max_total_tokens
        return self.synth.tokens + max(0, remaining["tokens"])

    def collect_findings(self, state, *, incremental=False):
        if not incremental:
            self.tick("collect_findings")
        records = list(state["investigation_results"])
        for raw in state["execution_records"]:
            assignment = raw.assignment
            if assignment.invocation_id in self._collected_records:
                records.append(self._collected_records[assignment.invocation_id])
                continue
            result = None
            status, error = raw.status, raw.error
            failure = raw.failure
            evidence = list(raw.evidence)
            usage = self.fallback_consumption(assignment)
            if status == "received":
                try:
                    spec = self.registry[assignment.investigator_id]
                    result = spec.result_class.model_validate(raw.value)
                    self.validate_collected_result(result, raw, state)
                    status = self.result_status(result)
                    usage = Consumption(model_calls=result.model_calls, tool_calls=result.tool_calls,
                        accounted_tokens=result.accounted_tokens, estimated_tokens=result.estimated_tokens)
                except Exception as exc:  # noqa: BLE001 - validate untrusted investigator output
                    from ...services.execution_failures import failure_from_exception
                    failure = failure_from_exception(exc, "validate_result", spec.result_class)
                    result, status, error, evidence = None, "failed", type(exc).__name__, []
                    error = failure.exception_type or error
            record = self.invocation_record_type(assignment=assignment, status=status, result=result, evidence=evidence,
                consumption=usage, error=error, failure=failure, duration_seconds=raw.duration_seconds,
                warnings=result.limitations if result else [])
            if result is not None and assignment.commitments and status == "completed" and not all(
                    commitment_resolved(c, self.project_record(record)) for c in assignment.commitments):
                record = record.model_copy(update={"status": "partial", "warnings": [*record.warnings,
                    "Follow-up did not validly resolve its assigned subjects/boundary/context; original task remains open."]})
            records.append(record)
            self._collected_records[assignment.invocation_id] = record
            self.synth.logger.info("%s invocation=%s investigator=%s round=%s status=%s duration=%.3f tokens=%s",
                self.trace_name, assignment.invocation_id, assignment.investigator_id, assignment.round, status,
                raw.duration_seconds, usage.accounted_tokens)
            self.spent = Consumption(**{field: getattr(self.spent, field) + getattr(usage, field)
                for field in ("model_calls", "tool_calls", "accounted_tokens", "estimated_tokens")},
                model_calls_estimated=self.spent.model_calls_estimated or usage.model_calls_estimated)
        return {"investigation_results": records, "completed_assignments": [r.assignment.invocation_id for r in records],
            "invocation_status": {r.assignment.invocation_id: r.status for r in records},
            "rounds_completed": state["rounds_completed"] + 1, "collected_count": len(records)}

    async def synthesize_findings(self, state):
        self.tick("synthesize_findings")
        records = state["investigation_results"]
        gaps = {g.id: g for g in state["material_gaps"]}
        resolved = set(state["resolved_gap_ids"])
        withdrawn = set(state["withdrawn_finding_refs"])
        projections = {r.assignment.invocation_id: self.project_record(r) for r in records}
        tasks = {r.assignment.invocation_id: task_specs(r, projections[r.assignment.invocation_id],
            self.source_issue_tokens, self.task_question) for r in records}
        for key in self.registry:
            calls = [r for r in records if r.assignment.investigator_id == key]
            gap_id = "essential-" + key
            if any(r.status == "completed" and r.assignment.round == 1 for r in calls):
                gaps.pop(gap_id, None)
            elif any(spec.get("commitments") for r in calls for spec in tasks[r.assignment.invocation_id]):
                # Subject-bound tasks replace a broad repeat of the initial audit.
                gaps.pop(gap_id, None)
            elif not any(r.status == "completed" and gap_id in r.assignment.gap_ids for r in calls):
                gaps[gap_id] = self.gap_type(id=gap_id, kind="essential_failure", investigator_id=key,
                    question=next(a.question for a in state["initial_plan"] if a.investigator_id == key), targets=self.request.targets)
            else:
                gaps.pop(gap_id, None)
                resolved.add(gap_id)
        for record in records:
            if record.result:
                for spec in tasks[record.assignment.invocation_id]:
                    if spec["id"] not in resolved:
                        gaps.setdefault(spec["id"], self.gap_type(**spec))
        for gap in self.detect_contradictions(records, withdrawn):
            if gap.id not in resolved:
                gaps[gap.id] = gap
        index = evidence_index(records)
        findings = self.finding_index(records)
        context = {"objective": self.request.objective, "scope": self.request.targets,
            "invocations": [{"invocation_id": r.assignment.invocation_id, "investigator_id": r.assignment.investigator_id,
                "status": r.status, "gap_ids": r.assignment.gap_ids, "error": r.error,
                "missing_information": r.result.missing_information if r.result else [], "warnings": r.warnings[:8],
                **projections[r.assignment.invocation_id]} for r in records],
            "findings": {ref: {"title": c.finding.title, "description": c.finding.description[:1200],
                "components": c.finding.components, "validation_status": c.finding.validation_status,
                "details": c.finding.model_dump(exclude={"evidence", "criterion"}),
                "evidence_refs": [f"{c.invocation_id}/{e.id}" for e in c.finding.evidence]} for ref, c in findings.items()},
            "evidence": {ref: e.model_dump() for ref, e in index.items()}, "gaps": [g.model_dump() for g in gaps.values()]}
        before = self.synth.calls, self.synth.tokens, self.synth.estimates
        remaining = self.resources()
        self.synth.call_limit = self.synth.calls + max(0, remaining["calls"])
        self.synth.token_limit = self.synthesis_token_limit(remaining)
        self.resume_synthesis()
        context = self.synthesis_context(context, state, records)
        draft = await self.synth.call("synthesize_findings", {"messages": [], "compact_context": context}, self.synthesis_draft_type)
        self.spent = self.spent.model_copy(update={"model_calls": self.spent.model_calls + self.synth.calls - before[0],
            "accounted_tokens": self.spent.accounted_tokens + self.synth.tokens - before[1],
            "estimated_tokens": self.spent.estimated_tokens + self.synth.estimates - before[2]})
        if draft:
            if "synthesis-failure" in gaps:
                gaps.pop("synthesis-failure")
                resolved.add("synthesis-failure")
            for resolution in draft.resolutions:
                gap = gaps.get(resolution.gap_id)
                record = next((r for r in records if r.assignment.invocation_id == resolution.invocation_id), None)
                new_refs = {f"{record.assignment.invocation_id}/{e.id}" for e in record.evidence if e.kind == "source"} if record else set()
                bound = bool(gap and record and gap.commitments and all(
                    commitment_resolved(c, projections[record.assignment.invocation_id]) for c in gap.commitments))
                repaired = bool(gap and record and validation_progress(gap, record, records, self.project_record))
                fresh = bool(record and new_source(resolution, record, records, index))
                # Repairs require a validated transition, not a fresh retrieval UUID.
                if (gap and record and (record.status == "completed" or bound and record.status == "partial")
                        and gap.id in record.assignment.gap_ids
                        and set(resolution.evidence_refs) <= new_refs
                        and (fresh or repaired) and (not gap.commitments or bound)
                        and set(resolution.withdrawn_finding_refs) <= set(gap.finding_refs)
                        and (gap.kind != "contradiction" or resolution.withdrawn_finding_refs)):
                    gaps.pop(gap.id)
                    resolved.add(gap.id)
                    withdrawn.update(resolution.withdrawn_finding_refs)
            for proposal in draft.gaps:
                if not set(proposal.evidence_refs) <= index.keys() or not set(proposal.finding_refs) <= findings.keys():
                    continue
                if any(t not in self.paths and not any(p.startswith(t.rstrip("/") + "/") for p in self.paths) for t in proposal.targets):
                    continue
                gid = stable_id("gap", [proposal.investigator_id, proposal.question.casefold(), sorted(proposal.targets)])
                if gid not in resolved:
                    commitments = {}
                    for ref in proposal.finding_refs:
                        contribution = findings[ref]
                        if contribution.investigator_id != proposal.investigator_id:
                            continue
                        finding = contribution.finding
                        ids = set(getattr(finding, "assessment_ids", []))
                        group_id = getattr(finding, "group_id", None)
                        for c in projections[contribution.invocation_id].get("commitments", []):
                            if ids & set(c["assessment_ids"]) or group_id and group_id in c["subject_ids"]:
                                commitments[stable_id("commitment", c)] = c
                    gaps[gid] = self.gap_type(id=gid, **proposal.model_dump(), commitments=list(commitments.values()),
                        task_type="contradiction" if proposal.kind == "contradiction" else "source_inspection" if commitments else "investigation")
        else:
            gaps["synthesis-failure"] = self.gap_type(id="synthesis-failure", kind="synthesis_failure",
                investigator_id=None, question="Synthesis unavailable: " + (self.synth.stop or "invalid_response"))
        values = list(gaps.values())
        return {"material_gaps": values, "actionable_followups": [g for g in values if self.actionable(g, records)],
            "resolved_gap_ids": sorted(resolved), "withdrawn_finding_refs": sorted(withdrawn),
            "consolidated_findings": self.consolidate(records, draft.groups if draft else [], values, withdrawn),
            "summary": draft.summary if draft else "Synthesis unavailable; retained investigator evidence only.",
            "budgets": {**self.resources(), "unlimited_token_budget": effective_token_budget_policy().unlimited_token_budget,
                "can_dispatch": self.can_dispatch(records)}}
