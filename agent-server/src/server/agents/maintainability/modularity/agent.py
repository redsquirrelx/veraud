"""Read-only hierarchical coordination with bounded conditional refinement."""

import asyncio
from itertools import pairwise
from pathlib import Path
from time import monotonic
from types import SimpleNamespace
from uuid import uuid4

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import END, START, StateGraph

from ....app.tracing_port import LangSmithTracingBackend
from ....benchmark.pacing import RequestPacer
from ...modularity_runtime.agent import InvestigationExecution
from ...modularity_runtime.provider import ProviderPacer, lean_schema
from ...repository_runtime.context import RepositoryContext
from ...repository_runtime.schemas import ExecutionBudget
from ...repository_runtime.tools import RepositoryToolset
from .registry import INVESTIGATORS
from .schemas import (
    Assignment,
    Consumption,
    EvidenceGap,
    InvocationRecord,
    ModularityAssessment,
    ModularityConfig,
    ModularityRequest,
    RawInvocation,
    SynthesisDraft,
)
from .state import ModularityState
from .synthesis import (
    actionable,
    consolidate,
    detect_contradictions,
    evidence_index,
    evidence_key,
    finding_index,
    request_key,
    stable_id,
)


def route_after_synthesis(state):
    """Explicit, state-only router; the model cannot override limits."""
    if not state["material_gaps"]:
        return "finalize"
    if not state["actionable_followups"]:
        return "finalize_limited" if any(g.kind == "essential_failure" for g in state["material_gaps"]) else "finalize"
    if state["rounds_completed"] >= state["max_rounds"] or not state["budgets"]["can_dispatch"]:
        return "finalize_limited"
    return "reinvestigate"


class _SynthesisExecution(InvestigationExecution):
    prompt_directory = Path(__file__).parent / "prompts"

    def _context(self, state):
        return state["compact_context"]

    def structured_schema(self, schema):
        # Bound-heavy nested JSON schemas can exceed Gemini's generation-state limit.
        # Preserve the full Pydantic contract for local validation after generation.
        return lean_schema(schema) if isinstance(self.model, BaseChatModel) else schema


class ModularityAgent:
    trace_name = "modularity"
    agent_type = "modularity"

    def __init__(self, model, config=None, *, tracing_backend=None, investigator_factory=None, provider_pacer=None):
        self.model = getattr(model, "llm", model)
        self.config = config or ModularityConfig()
        if set(self.config.prompts) - {"synthesize_findings"}:
            raise ValueError("Coordinator prompt overrides must name synthesize_findings.")
        self.tracing = tracing_backend or LangSmithTracingBackend()
        self.factory = investigator_factory
        self.provider_pacer = provider_pacer

    async def run(self, tools, request=None):
        if tools.budget_usage.tool_calls:
            raise ValueError("Use a fresh RepositoryToolset for the coordinator.")
        execution = _Execution(self, tools, request or ModularityRequest())
        state = await execution.graph.ainvoke(execution.initial_state(), {"recursion_limit": 12 * self.config.max_rounds + 20})
        return state["result"]


class _Execution:
    # Contract/registry hooks let sibling coordinators reuse dispatch, accounting
    # and synthesis without changing modularity's existing graph or defaults.
    registry = INVESTIGATORS
    assignment_type = Assignment
    raw_invocation_type = RawInvocation
    invocation_record_type = InvocationRecord
    gap_type = EvidenceGap
    synthesis_draft_type = SynthesisDraft
    synthesis_execution_type = _SynthesisExecution
    finding_index = staticmethod(finding_index)
    detect_contradictions = staticmethod(detect_contradictions)
    consolidate = staticmethod(consolidate)
    actionable = staticmethod(actionable)

    def __init__(self, agent, tools, request):
        self.agent, self.tools, self.request = agent, tools, request
        self.config = agent.config
        self.started = monotonic()
        self.transitions = []
        self.spent = Consumption()
        self.global_budget = tools.context.input.budget
        self.synth = self.synthesis_execution_type(agent.model, self.config, tools, request)
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
        self.synth.logger.info("modularity node=%s", name)

    def remaining(self):
        return min(self.config.timeout_seconds - (monotonic() - self.started),
                   self.global_budget.max_elapsed_seconds - self.tools.context.elapsed_seconds)

    def resources(self):
        return {
            "calls": min(self.config.max_model_calls, self.global_budget.max_model_calls) - self.spent.model_calls,
            "tokens": min(self.config.max_total_tokens, self.global_budget.max_total_tokens,
                          self.global_budget.max_tokens_per_objective) - self.spent.accounted_tokens,
            "tools": min(self.config.max_tool_calls, self.global_budget.max_tool_calls) - self.spent.tool_calls,
        }

    def can_dispatch(self, records):
        remaining = self.resources()
        # Reserve the whole per-invocation envelope before dispatch, not after parallel calls.
        limits = self.config.invocation_limits
        return (len(records) < self.config.max_invocations and self.remaining() > 0
                and remaining["calls"] >= limits.max_model_calls
                and remaining["tokens"] >= limits.max_total_tokens
                and remaining["tools"] >= limits.max_tool_calls)

    def initial_state(self):
        return {"assessment_id": uuid4().hex, "repository_id": self.tools.accessible_snapshot.repository.name,
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
        self.tick("delegate_investigations")
        semaphore = asyncio.Semaphore(self.config.max_parallel)
        reserved = dict(self.resources())
        existing = len(state["investigation_results"])
        limits = self.config.invocation_limits
        dispatch = []
        for assignment in state["pending_assignments"]:
            if (existing + len(dispatch) >= self.config.max_invocations or self.remaining() <= 0
                    or reserved["calls"] < limits.max_model_calls or reserved["tokens"] < limits.max_total_tokens
                    or reserved["tools"] < limits.max_tool_calls):
                dispatch.append((assignment, None))
                continue
            budget = ExecutionBudget(
                max_model_calls=limits.max_model_calls, max_total_tokens=limits.max_total_tokens,
                max_tokens_per_objective=limits.max_total_tokens,
                max_tool_calls=max(1, limits.max_tool_calls),
                max_input_tokens_per_call=min(self.global_budget.max_input_tokens_per_call, limits.max_context_characters // 2),
                max_output_tokens_per_call=min(self.global_budget.max_output_tokens_per_call, limits.max_output_tokens),
                max_retrieved_characters=max(1, self.global_budget.max_retrieved_characters // self.config.max_invocations),
                max_elapsed_seconds=min(limits.timeout_seconds, self.remaining()),
            )
            reserved["calls"] -= limits.max_model_calls
            reserved["tokens"] -= limits.max_total_tokens
            reserved["tools"] -= limits.max_tool_calls
            dispatch.append((assignment.model_copy(update={"budget": budget}), budget))

        async def invoke(assignment, budget):
            if budget is None:
                return self.raw_invocation_type(assignment=assignment, status="skipped", error="execution_budget_exhausted")
            async with semaphore:
                started = monotonic()
                try:
                    async def wait_for_start():
                        async with self.investigation_start_pacer.lock:
                            await self.investigation_start_pacer.wait()
                            self.investigation_start_pacer.completed_attempt()
                    await asyncio.wait_for(wait_for_start(), max(0, self.remaining()))
                except TimeoutError:
                    # No investigator was started: do not charge its reserved envelope.
                    return self.raw_invocation_type(assignment=assignment.model_copy(update={"budget": None}),
                        status="skipped", error="assessment_time_exhausted", duration_seconds=monotonic() - started)
                child = None
                try:
                    if self.remaining() <= 0:
                        raise TimeoutError
                    spec = self.registry[assignment.investigator_id]
                    child = RepositoryToolset(RepositoryContext(self.tools.context.snapshot,
                        self.tools.context.input.model_copy(update={"budget": budget})),
                        workspace_root=self.tools.policy.workspace_root, limits=self.tools.limits)
                    config = self.invocation_config(spec, limits)
                    investigator = (self.agent.factory(assignment.investigator_id, self.agent.model, config)
                                    if self.agent.factory else spec.agent_class(self.agent.model, config,
                                        provider_pacer=self.provider_pacer))
                    self.configure_invocation(investigator, assignment, state)
                    index = self.prior_evidence_index(state["investigation_results"])
                    context = self.request.architectural_context + "\nScoped targets: " + ", ".join(assignment.targets)
                    context += "\nPrior evidence references (navigation only; retrieve and verify): " + str([
                        index[ref].model_dump() for ref in assignment.evidence_refs[:8] if ref in index])
                    value = await asyncio.wait_for(self.agent.tracing.wrap_stage(
                        investigator.run(child, self.investigator_request(spec, assignment, context)),
                        **self.invocation_metadata(assignment, state)), min(budget.max_elapsed_seconds, self.remaining()))
                    return self.raw_invocation_type(assignment=assignment, status="received", value=value,
                        evidence=self.invocation_evidence(value, child),
                        duration_seconds=monotonic() - started)
                except Exception as error:  # noqa: BLE001 - investigator boundary; cancellation propagates
                    return self.raw_invocation_type(assignment=assignment, status="timeout" if isinstance(error, TimeoutError) else "failed",
                        error=type(error).__name__, duration_seconds=monotonic() - started,
                        evidence=self.references(child) if child else [])

        raw = await asyncio.gather(*(invoke(a, b) for a, b in dispatch))
        return {"execution_records": raw, "pending_assignments": []}

    @staticmethod
    def references(tools):
        # Reuse the investigators' provenance adapter, including metadata and line ranges.
        return InvestigationExecution.references(SimpleNamespace(tools=tools))

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
        return {"name": "modularity-investigation", "invocation_id": assignment.invocation_id,
                "investigator_id": assignment.investigator_id, "round": assignment.round,
                "snapshot_hash": state["snapshot_hash"]}

    def validate_collected_result(self, result, raw, state):
        snapshot = self.tools.accessible_snapshot
        if (result.snapshot_hash != state["snapshot_hash"] or result.commit != snapshot.repository.commit
                or result.repository_id != snapshot.repository.name or result.objective != raw.assignment.question):
            raise ValueError("Mismatched repository provenance")
        files = {f.id: f for f in snapshot.files}
        for finding in result.findings:
            for ref in finding.evidence:
                if (ref.snapshot_hash != state["snapshot_hash"] or ref.commit != result.commit
                        or ref.file_id not in files or files[ref.file_id].path != ref.path
                        or files[ref.file_id].content_hash != ref.content_hash):
                    raise ValueError("Mismatched evidence provenance")

    def result_status(self, result):
        return "completed" if (result.termination_reason == "sufficient_evidence" and result.plan
            and not result.missing_information and not any(h.status in {"pending", "inconclusive"} for h in result.hypotheses)
            and not getattr(result, "inconclusive_investigations", [])
            and not any(f.validation_status == "insufficient_evidence" for f in result.findings)) else "partial"

    def synthesis_context(self, context, state, records):
        return context

    def collect_findings(self, state):
        self.tick("collect_findings")
        records = list(state["investigation_results"])
        for raw in state["execution_records"]:
            assignment = raw.assignment
            result = None
            status, error = raw.status, raw.error
            evidence = list(raw.evidence)
            usage = Consumption()
            if assignment.budget:
                # Unknown failures consume their reservation; never silently refund expensive calls.
                usage = Consumption(model_calls=assignment.budget.max_model_calls,
                    tool_calls=assignment.budget.max_tool_calls, accounted_tokens=assignment.budget.max_total_tokens,
                    estimated_tokens=assignment.budget.max_total_tokens, model_calls_estimated=True)
            if status == "received":
                try:
                    spec = self.registry[assignment.investigator_id]
                    result = spec.result_class.model_validate(raw.value)
                    self.validate_collected_result(result, raw, state)
                    for finding in result.findings:
                        evidence.extend(finding.evidence)
                    status = self.result_status(result)
                    usage = Consumption(model_calls=result.model_calls, tool_calls=result.tool_calls,
                        accounted_tokens=result.accounted_tokens, estimated_tokens=result.estimated_tokens)
                except Exception as exc:  # noqa: BLE001 - validate untrusted investigator output
                    result, status, error, evidence = None, "failed", type(exc).__name__, []
            record = self.invocation_record_type(assignment=assignment, status=status, result=result, evidence=evidence,
                consumption=usage, error=error, duration_seconds=raw.duration_seconds,
                warnings=result.limitations if result else [])
            records.append(record)
            self.synth.logger.info("%s invocation=%s investigator=%s round=%s status=%s duration=%.3f tokens=%s",
                self.agent.trace_name, assignment.invocation_id, assignment.investigator_id, assignment.round, status,
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
        self.synth.token_limit = self.synth.tokens + max(0, remaining["tokens"])
        if self.synth.retryable_failure:
            # A later evidence round may recover after a transient provider outage.
            # Do not reset counters, deadlines or permanent request/schema failures.
            self.synth.stop = ""
            self.synth.retryable_failure = False
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

    def decide_next_step(self, state):
        self.tick("decide_next_step")
        route = route_after_synthesis(state)
        reason = ("essential_investigation_failed" if not state["actionable_followups"] else
                  "round_limit" if state["rounds_completed"] >= self.config.max_rounds else "resource_limit") if route == "finalize_limited" else (
            "targeted_follow_up" if route == "reinvestigate" else "unresolved_no_useful_follow_up" if state["material_gaps"] else "sufficient_evidence")
        return {"next_route": route, "termination_reason": reason}

    def plan_targeted_follow_up(self, state):
        self.tick("plan_targeted_follow_up")
        grouped = {}
        for gap in state["actionable_followups"]:
            key = request_key(gap.investigator_id, gap.question, gap.targets)
            grouped.setdefault(key, []).append(gap)
        plan = [self.assignment(group[0].investigator_id, group[0].question, state["rounds_completed"] + 1,
            group[0].targets, list(dict.fromkeys(ref for g in group for ref in g.evidence_refs))[:8],
            [g.id for g in group]) for group in list(grouped.values())[:3]]
        return {"pending_assignments": plan}

    def finalize_assessment(self, state):
        self.tick("finalize_assessment")
        records = state["investigation_results"]
        usable = any(r.result is not None for r in records)
        status = "completed" if not state["material_gaps"] and usable else "partial" if usable else "failed"
        limitations = list(dict.fromkeys([g.question for g in state["material_gaps"]] +
            [warning for r in records for warning in r.warnings] + self.synth.issues))
        return {"result": ModularityAssessment(
            assessment_id=state["assessment_id"], repository_id=state["repository_id"],
            commit=self.tools.accessible_snapshot.repository.commit, snapshot_hash=state["snapshot_hash"],
            objective=self.request.objective, targets=self.request.targets, status=status,
            termination_reason=state["termination_reason"], summary=state["summary"],
            investigator_registry=state["investigator_registry"], initial_plan=state["initial_plan"],
            invocations=records, consolidated_findings=state["consolidated_findings"],
            material_gaps=state["material_gaps"], resolved_gap_ids=state["resolved_gap_ids"],
            withdrawn_finding_refs=state["withdrawn_finding_refs"], limitations=limitations,
            rounds_completed=state["rounds_completed"], consumption=self.spent,
            duration_seconds=monotonic() - self.started, node_transitions=self.transitions)}

    def build_graph(self):
        graph = StateGraph(ModularityState)
        nodes = ["plan_assessment", "delegate_investigations", "collect_findings", "synthesize_findings",
                 "decide_next_step", "plan_targeted_follow_up", "finalize_assessment"]
        for name in nodes:
            graph.add_node(name, getattr(self, name))
        graph.add_edge(START, "plan_assessment")
        for source, target in pairwise(nodes[:5]):
            graph.add_edge(source, target)
        graph.add_conditional_edges("decide_next_step", lambda state: state["next_route"], {
            "reinvestigate": "plan_targeted_follow_up", "finalize": "finalize_assessment",
            "finalize_limited": "finalize_assessment"})
        graph.add_edge("plan_targeted_follow_up", "delegate_investigations")
        graph.add_edge("finalize_assessment", END)
        return graph.compile()
