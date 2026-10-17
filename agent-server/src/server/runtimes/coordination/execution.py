"""Read-only hierarchical coordination with bounded conditional refinement."""

import asyncio
from abc import ABC, abstractmethod
from time import monotonic
from types import SimpleNamespace
from typing import TYPE_CHECKING
from uuid import uuid4

from langchain_core.language_models.chat_models import BaseChatModel

from ...app.tracing_port import LangSmithTracingBackend
from ...benchmark.pacing import RequestPacer
from ...blackboard.publication import publication_for
from ..investigation.agent import InvestigationExecution
from ..investigation.provider import ProviderPacer, lean_schema
from ..repository.context import RepositoryContext
from ..repository.schemas import ExecutionBudget
from ..repository.timing import ActiveDeadline, within_deadline
from ..repository.tools import RepositoryToolset
from .schemas import Consumption
from .synthesis import (
    evidence_index,
    evidence_key,
    stable_id,
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
        self.config = config or self.config_type()
        if set(self.config.prompts) - set(self.config.prompt_nodes):
            raise ValueError("Coordinator prompt overrides must name configured cognitive nodes.")
        self.tracing = tracing_backend or LangSmithTracingBackend()
        self.factory = investigator_factory
        self.provider_pacer = provider_pacer
        self.blackboard = blackboard
        self.audit_identity = audit_identity

class CoordinatorExecution(ABC):
    """Shared dispatch, reservations, provenance, collection and synthesis.

    Concrete coordinators bind their own registry, contracts, policies and graph.
    No audit dimension is imported or selected by this runtime.
    """

    @abstractmethod
    def build_graph(self):
        """Bind the concrete coordinator's topology and output contract."""

    def __init__(self, agent, tools, request):
        self.agent, self.tools, self.request = agent, tools, request
        self.blackboard = getattr(agent, "blackboard", None)
        self.publication = publication_for(agent) if self.blackboard is not None else None
        self.audit_identity = self.publication.identity if self.publication is not None else getattr(agent, "audit_identity", None)
        self.trace_name = getattr(agent, "trace_name", "coordinator")
        self.config = agent.config
        self.started = monotonic()
        self.transitions = []
        self.spent = Consumption()
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
        self.provider_pacer = getattr(agent, "provider_pacer", None) or ProviderPacer(rate_limits=self.config.provider_rate_limits,
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
        return (len(records) < self.config.max_invocations and self.remaining() > 0
                and remaining["calls"] >= limits.max_model_calls
                and remaining["tokens"] >= (1 if self.token_budget is not None else limits.max_total_tokens)
                and remaining["tools"] >= limits.max_tool_calls)

    def initial_state(self):
        return {"assessment_id": self.assessment_identity(), "repository_id": self.tools.accessible_snapshot.repository.name,
            "snapshot_hash": self.tools.context.input.snapshot_hash, "scope": self.request.targets,
            "investigator_registry": [s.capability for s in self.registry.values()], "rounds_completed": 0,
            "max_rounds": self.config.max_rounds, "budgets": {}, "pending_assignments": [], "completed_assignments": [],
            "invocation_status": {}, "investigation_results": [], "execution_records": [], "collected_count": 0,
            "initial_plan": [], "consolidated_findings": [], "material_gaps": [], "actionable_followups": [],
            "resolved_gap_ids": [], "withdrawn_finding_refs": [], "summary": "", "messages": [], "termination_reason": ""}

    def assignment(self, investigator, question, round_number, targets, refs=None, gaps=None):
        return self.assignment_type(invocation_id=uuid4().hex, investigator_id=investigator, round=round_number,
                          question=question, targets=targets, evidence_refs=refs or [], gap_ids=gaps or [])

    def plan_assessment(self, state):
        self.tick("plan_assessment")
        plan = [self.assignment(key, self.request.objective + "\n" + spec.capability.capability,
                               1, self.request.targets) for key, spec in self.registry.items()]
        return {"pending_assignments": plan, "initial_plan": plan}

    async def delegate_investigations(self, state):
        from ...services.execution_failures import (
            ExecutionFailure,
            ResourceShortfall,
            failure_from_exception,
        )

        self.tick("delegate_investigations")
        semaphore = asyncio.Semaphore(self.config.max_parallel)
        reserved = dict(self.resources())
        existing = len(state["investigation_results"])
        limits = self.config.invocation_limits
        dispatch = []
        failures = {}
        for assignment in state["pending_assignments"]:
            requirements = [("invocations", self.config.max_invocations - existing - len(dispatch), 1),
                ("seconds", self.remaining(), 0.001), ("calls", reserved["calls"], limits.max_model_calls),
                ("tokens", reserved["tokens"], 1 if self.token_budget is not None else limits.max_total_tokens),
                ("tools", reserved["tools"], limits.max_tool_calls)]
            shortfalls = [ResourceShortfall(resource=key, available=max(0, available), required=required)
                for key, available, required in requirements if available < required]
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
                max_output_tokens_per_call=min(self.global_budget.max_output_tokens_per_call, limits.max_output_tokens),
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
                    agent_models = getattr(self.agent, "agent_models", {})
                    selected_model = agent_models.get(assignment.investigator_id, self.agent.model)
                    investigator = (self.agent.factory(assignment.investigator_id, selected_model, config)
                                    if self.agent.factory else spec.agent_class(selected_model, config,
                                        provider_pacer=self.provider_pacer))
                    investigator.agent_models = agent_models
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
                    value = await within_deadline(within_deadline(self.agent.tracing.wrap_stage(
                        investigator.run(child, self.investigator_request(spec, assignment, context)),
                        **self.invocation_metadata(assignment, state)), timing), self.timing)
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
        args = {"objective": assignment.question, "architectural_context": context}
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
        for key in self.registry:
            calls = [r for r in records if r.assignment.investigator_id == key]
            gap_id = "essential-" + key
            if any(r.status == "completed" and r.assignment.round == 1 for r in calls):
                gaps.pop(gap_id, None)
            elif not any(r.status == "completed" and gap_id in r.assignment.gap_ids for r in calls):
                gaps[gap_id] = self.gap_type(id=gap_id, kind="essential_failure", investigator_id=key,
                    question=next(a.question for a in state["initial_plan"] if a.investigator_id == key), targets=self.request.targets)
            else:
                gaps.pop(gap_id, None)
                resolved.add(gap_id)
        for record in records:
            if record.result:
                for question in record.result.missing_information:
                    gid = stable_id("missing", [record.assignment.invocation_id, question])
                    if gid not in resolved:
                        gaps[gid] = self.gap_type(id=gid, kind="missing_evidence", investigator_id=record.assignment.investigator_id,
                            question=question, targets=record.assignment.targets)
        for gap in self.detect_contradictions(records, withdrawn):
            if gap.id not in resolved:
                gaps[gap.id] = gap
        index = evidence_index(records)
        findings = self.finding_index(records)
        context = {"objective": self.request.objective, "scope": self.request.targets,
            "invocations": [{"invocation_id": r.assignment.invocation_id, "investigator_id": r.assignment.investigator_id,
                "status": r.status, "gap_ids": r.assignment.gap_ids, "error": r.error,
                "missing_information": r.result.missing_information if r.result else [], "warnings": r.warnings[:8]} for r in records],
            "findings": {ref: {"title": c.finding.title, "description": c.finding.description[:1200],
                "components": c.finding.components, "validation_status": c.finding.validation_status,
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
                old_keys = {evidence_key(index[r]) for r in gap.evidence_refs if r in index} if gap else set()
                if (gap and record and record.status == "completed" and gap.id in record.assignment.gap_ids
                        and set(resolution.evidence_refs) <= new_refs
                        and any(evidence_key(index[r]) not in old_keys for r in resolution.evidence_refs)
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
                    gaps[gid] = self.gap_type(id=gid, **proposal.model_dump())
        else:
            gaps["synthesis-failure"] = self.gap_type(id="synthesis-failure", kind="synthesis_failure",
                investigator_id=None, question="Synthesis unavailable: " + (self.synth.stop or "invalid_response"))
        values = list(gaps.values())
        return {"material_gaps": values, "actionable_followups": [g for g in values if self.actionable(g, records)],
            "resolved_gap_ids": sorted(resolved), "withdrawn_finding_refs": sorted(withdrawn),
            "consolidated_findings": self.consolidate(records, draft.groups if draft else [], values, withdrawn),
            "summary": draft.summary if draft else "Synthesis unavailable; retained investigator evidence only.",
            "budgets": {**self.resources(), "can_dispatch": self.can_dispatch(records)}}
