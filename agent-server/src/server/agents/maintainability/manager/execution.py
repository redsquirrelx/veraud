"""Hierarchical maintainability audit with exact bounded coverage-refinement topology."""

import logging
from pathlib import Path
from time import monotonic
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from ....runtimes.coordination.continuation import CoordinatorContinuation
from ....runtimes.coordination.execution import (
    CoordinatorExecution,
    CoordinatorSynthesisExecution,
)
from ....runtimes.coordination.schemas import Consumption
from ....runtimes.coordination.synthesis import (
    evidence_key,
    stable_id,
    terminal_collection_blocker,
    terminal_provider_blocker,
)
from ....runtimes.investigation.schemas import EvidenceReference
from ..modularity.coordinator.registry import INVESTIGATORS as MODULARITY_INVESTIGATORS
from ..reusability.coordinator.registry import (
    INVESTIGATORS as REUSABILITY_INVESTIGATORS,
)
from . import synthesis, validation
from .registry import COORDINATORS
from .schemas import (
    AssessmentLink,
    AssessmentSynthesis,
    AuditAssignment,
    CoordinatorAssessment,
    CoverageDecision,
    CoverageGap,
    MaintainabilityReport,
    RawAssessment,
    ScopeAssessment,
    SynthesisRound,
)
from .state import MaintainabilityManagerState

CRITERIA = ["Completed assessment without unresolved material gaps.",
            "Each registered investigator completed a planned source-backed investigation.",
            "All source references match the immutable snapshot and collected provenance."]


def coverage_router(state):
    """yes means finalize, including forced stops; sufficient is a separate truth value."""
    decision = state["decision"]
    if decision.sufficient or not decision.can_follow_up or not state["actionable_followups"]:
        return "yes"
    return "no"


class _ManagerSynthesis(CoordinatorSynthesisExecution):
    prompt_directory = Path(__file__).parent / "prompts"
    trace_name = "maintainability-manager-synthesis"


class _CorrelatedTracing:
    def __init__(self, backend, audit_id, attempt_id):
        self.backend, self.audit_id, self.attempt_id = backend, audit_id, attempt_id

    async def wrap_stage(self, coro, *, name, **metadata):
        return await self.backend.wrap_stage(coro, name=name, **(metadata | {
            "audit_id": self.audit_id, "coordinator_attempt_id": self.attempt_id}))

    async def wrap_pipeline(self, coro, *, name, **metadata):
        return await self.backend.wrap_pipeline(coro, name=name, **(metadata | {
            "audit_id": self.audit_id, "coordinator_attempt_id": self.attempt_id}))


class MaintainabilityManagerExecution(CoordinatorExecution):
    registry = COORDINATORS
    raw_invocation_type = RawAssessment
    synthesis_execution_type = _ManagerSynthesis

    def tick(self, name):
        name = {"delegate_investigations": "delegate_auditors"}.get(name, name)
        self.transitions.append(name)
        logging.getLogger(__name__).info("maintainability manager node=%s", name)

    def initial_state(self):
        self.audit_id = self.assessment_identity()
        return {"assessment_id": self.audit_id, "repository_id": self.tools.accessible_snapshot.repository.name,
            "snapshot_hash": self.tools.context.input.snapshot_hash, "initial_plan": [], "pending_assignments": [],
            "execution_records": [], "investigation_results": [], "rounds_completed": 0, "material_gaps": [],
            "resolved_gap_ids": [], "actionable_followups": [], "synthesis_history": [], "summary": "", "links": [],
            "ignored_responses": [], "issued_assignments": []}

    def analyze_audit_scope(self, state):
        self.tick("analyze_audit_scope")
        for dimension, targets in self.request.dimension_targets.items():
            if dimension not in self.request.dimensions or not 1 <= len(targets) <= 12:
                raise ValueError("Per-dimension targets require a selected dimension and 1-12 paths")
            for target in targets:
                if (target not in self.paths and not any(p.startswith(target + "/") for p in self.paths)
                        or self.request.targets and not any(target == t or target.startswith(t + "/") for t in self.request.targets)):
                    raise ValueError("Per-dimension target is inaccessible or outside the requested scope")
        scope = ScopeAssessment(repository_id=state["repository_id"], commit=self.tools.accessible_snapshot.repository.commit,
            snapshot_hash=state["snapshot_hash"], requested=self.request.dimensions,
            assessable=[d for d in self.request.dimensions if d in self.registry],
            unsupported=[d for d in self.request.dimensions if d not in self.registry],
            targets=self.request.targets, depth=self.request.depth)
        return {"scope": scope}

    def assignment(self, key, question, round_number, targets, gap_ids=None, evidence_refs=None, attempt=1):
        return AuditAssignment(assignment_id=uuid4().hex, invocation_id=uuid4().hex, investigator_id=key,
            question=question, round=round_number, attempt=attempt, targets=targets, gap_ids=gap_ids or [],
            evidence_refs=evidence_refs or [], requested_evidence=["Source-backed investigator results with preserved counterevidence and limitations."],
            success_criteria=CRITERIA)

    def plan_audit(self, state):
        self.tick("plan_audit")
        plan = [self.assignment(d, self.request.objective + f"\nAssess only {d} within the declared scope.",
            1, self.request.dimension_targets.get(d, self.request.targets)) for d in state["scope"].assessable]
        return {"initial_plan": plan, "pending_assignments": plan, "issued_assignments": plan}

    async def delegate_auditors(self, state):
        return await super().delegate_investigations(state)

    def invocation_config(self, spec, limits):
        return spec.config_class.model_validate(limits.model_dump())

    def configure_investigator(self, investigator):
        investigator.provider_pacer = self.provider_pacer

    def configure_invocation(self, investigator, assignment, state):
        self.configure_investigator(investigator)
        investigator.tracing = _CorrelatedTracing(self.agent.tracing, state["assessment_id"], assignment.invocation_id)
        if assignment.baseline_invocation_id:
            previous = next(r for r in state["investigation_results"] if r.assignment.invocation_id == assignment.baseline_invocation_id)
            publication = self.publication.child(previous.assignment.invocation_id, assignment.investigator_id) if self.publication else None
            investigator.continuation = CoordinatorContinuation(previous.result, tuple(assignment.subordinate_gap_ids), publication)

    def investigator_request(self, spec, assignment, context):
        context = context[:3500]
        context += f"\nAudit correlation: {self.audit_id}; assignment: {assignment.assignment_id}; attempt: {assignment.invocation_id}."
        context += "\nCoverage criteria: " + "; ".join(assignment.success_criteria)
        context += "\nRequested depth: " + self.request.depth + "; configured resource limits are authoritative."
        args = {"objective": assignment.question, "targets": assignment.targets,
                "architectural_context": context[:6000], "criteria": self.request.criteria,
                "follow_up": assignment.commitments, "follow_up_diagnostics": assignment.diagnostics}
        if assignment.investigator_id == "reusability":
            args["target_context"] = self.request.target_context
        return spec.request_class(**args)

    def invocation_metadata(self, assignment, state):
        return {"name": "maintainability-coordinator", "audit_id": state["assessment_id"],
            "assignment_id": assignment.assignment_id, "invocation_id": assignment.invocation_id,
            "attempt": assignment.attempt, "round": assignment.round, "coordinator": assignment.investigator_id,
            "snapshot_hash": state["snapshot_hash"]}

    def invocation_evidence(self, value, child):
        # The coordinator's own ledger is empty; collection derives evidence only
        # after the full nested assessment has passed schema/provenance validation.
        return []

    def prior_evidence_index(self, records):
        return self.indexes(records)[1]

    def valid_reference(self, ref):
        return validation.valid_reference(ref, self.tools)

    def validate_result(self, result, assignment):
        validation.validate_assessment(
            result, assignment, snapshot=self.tools.accessible_snapshot.repository,
            request=self.request, check_reference=self.valid_reference,
            verify_references=self.synth.verify_references,
            baseline=self.baseline_result(assignment),
        )

    def baseline_result(self, assignment):
        if not assignment.baseline_invocation_id:
            return None
        record = self._collected_records.get(assignment.baseline_invocation_id)
        if record is None or record.result is None or record.assignment.investigator_id != assignment.investigator_id:
            raise ValueError("Unknown coordinator continuation baseline.")
        return record.result

    def coverage_issues(self, result, key):
        registry = MODULARITY_INVESTIGATORS if key == "modularity" else REUSABILITY_INVESTIGATORS
        return validation.coverage_issues(result, registry)

    def collect_received(self, raw, state):
        update = self.collect_assessments(dict(state, execution_records=[raw]), incremental=True)
        record = next((r for r in update["investigation_results"] if r.assignment.invocation_id == raw.assignment.invocation_id), None)
        if record is not None:
            self.publish_collected(record)

    def publish_received_result(self, child, record):
        child.publish_assessment(record.result)

    def collect_assessments(self, state, *, incremental=False):
        if not incremental:
            self.tick("collect_assessments")
        records = list(state["investigation_results"])
        seen = {r.assignment.invocation_id for r in records}
        issued = {a.invocation_id: a for a in state["issued_assignments"]}
        ignored = list(state["ignored_responses"])
        for raw in state["execution_records"]:
            assignment = raw.assignment
            expected = issued.get(assignment.invocation_id)
            if (assignment.invocation_id in seen or expected is None or assignment.round != state["rounds_completed"] + 1
                    or assignment.model_dump(exclude={"budget"}) != expected.model_dump(exclude={"budget"})):
                ignored.append(assignment.invocation_id)
                continue
            seen.add(assignment.invocation_id)
            if assignment.invocation_id in self._collected_records:
                records.append(self._collected_records[assignment.invocation_id])
                continue
            usage = self.fallback_consumption(assignment)
            status, error, result, issues = raw.status, raw.error, None, []
            failure = raw.failure
            if status == "received":
                try:
                    value = raw.value.model_dump() if hasattr(raw.value, "model_dump") else raw.value
                    result = self.registry[assignment.investigator_id].result_class.model_validate(value)
                    # Evidence rejection does not erase valid, bounded usage already
                    # reported by the host coordinator. Invalid accounting retains
                    # the conservative reservation fallback.
                    usage = validation.validate_accounting(result, assignment.budget, baseline=self.baseline_result(assignment))
                    self.validate_result(result, assignment)
                    issues = self.coverage_issues(result, assignment.investigator_id)
                    status = "completed" if not issues else "failed" if result.status == "failed" else "partial"
                except Exception as exc:  # noqa: BLE001 - untrusted subordinate boundary
                    from ....services.execution_failures import failure_from_exception
                    failure = failure_from_exception(exc, "validate_assessment", self.registry[assignment.investigator_id].result_class)
                    result, status, error = None, "failed", type(exc).__name__
                    error = failure.exception_type or error
            evidence = [e for r in result.invocations for e in r.evidence] if result else []
            record = CoordinatorAssessment(assignment=assignment, result=result, status=status, error=error, failure=failure,
                evidence=evidence, consumption=usage, duration_seconds=raw.duration_seconds,
                warnings=result.limitations if result else [], coverage_issues=issues, evidence_sufficient=status == "completed")
            records.append(record)
            self._collected_records[assignment.invocation_id] = record
            self.spent = Consumption(**{k: getattr(self.spent, k) + getattr(usage, k)
                for k in ("model_calls", "tool_calls", "accounted_tokens", "estimated_tokens")},
                model_calls_estimated=self.spent.model_calls_estimated or usage.model_calls_estimated)
        return {"investigation_results": records,
                "rounds_completed": state["rounds_completed"] + int(len(records) > len(state["investigation_results"])),
                "ignored_responses": ignored}

    @staticmethod
    def indexes(records):
        return synthesis.assessment_indexes(records)

    def actionable(self, gap, records):
        if not gap.blocking or gap.coordinator is None:
            return False
        calls = [r for r in records if r.assignment.investigator_id == gap.coordinator]
        if gap.task_type == "external_context" or len(calls) >= self.config.max_attempts_per_dimension:
            return False
        if gap.source_assessment_invocation_id:
            source = next((r for r in calls if r.assignment.invocation_id == gap.source_assessment_invocation_id), None)
            if source is None or source.result is None or source.failure is not None:
                return False
            return any(g.id in gap.subordinate_gap_ids and self.registry[gap.coordinator].agent_class.continuation_actionable(source.result, g)
                for g in source.result.material_gaps)
        if calls and terminal_collection_blocker(calls[-1]):
            return False
        if calls and terminal_provider_blocker(calls[-1].result):
            return False
        if len(calls) >= self.config.max_attempts_per_dimension:
            return False
        return not any(r.assignment.question.strip().casefold() == gap.question.strip().casefold()
                       and r.assignment.targets == gap.targets for r in calls)

    def progress(self, state):
        if state["rounds_completed"] <= 1:
            return True
        prior = [r for r in state["investigation_results"] if r.assignment.round < state["rounds_completed"]]
        latest = [r for r in state["investigation_results"] if r.assignment.round == state["rounds_completed"]]
        known = {evidence_key(e) for r in prior for e in r.evidence if e.kind == "source"}
        return (any(e.kind == "source" and evidence_key(e) not in known for r in latest for e in r.evidence)
                or any(r.result and r.assignment.baseline_invocation_id and any(
                    p.assignment.invocation_id == r.assignment.baseline_invocation_id and p.result
                    and set(r.result.resolved_gap_ids) - set(p.result.resolved_gap_ids) for p in prior) for r in latest)
                or any(r.evidence_sufficient and not any(p.evidence_sufficient and p.assignment.investigator_id == r.assignment.investigator_id
                       for p in prior) for r in latest))

    async def synthesize_assessments(self, state):
        self.tick("synthesize_assessments")
        records = state["investigation_results"]
        findings, evidence = self.indexes(records)
        latest = {r.assignment.investigator_id: r for r in records}
        covered = [d for d in state["scope"].assessable if d in latest and latest[d].evidence_sufficient]
        resolved = set(state["resolved_gap_ids"])
        gaps = {g.id: g for g in state["material_gaps"] if g.subordinate_gap_ids or g.kind not in {"missing_coverage", "synthesis_failure"}}
        for gap in list(gaps.values()):
            current = latest.get(gap.coordinator)
            if (gap.subordinate_gap_ids and current and current.result and
                    (set(gap.subordinate_gap_ids) <= set(current.result.resolved_gap_ids) or current.evidence_sufficient)):
                gaps.pop(gap.id)
                resolved.add(gap.id)
        for dimension in state["scope"].assessable:
            if dimension not in covered:
                calls = [r for r in records if r.assignment.investigator_id == dimension]
                current = latest.get(dimension)
                tasks = synthesis.subordinate_tasks(current, findings, evidence) if current and current.result else []
                if tasks:
                    for task in tasks:
                        if task.id not in resolved:
                            gaps[task.id] = task
                    continue
                details = "; ".join(calls[-1].coverage_issues) if calls else "No result"
                gap = CoverageGap(id="coverage-" + dimension, kind="missing_coverage", coordinator=dimension,
                    question=f"Complete the missing source-backed {dimension} coverage. {details}",
                    targets=self.request.dimension_targets.get(dimension, self.request.targets))
                gaps[gap.id] = gap
        for dimension in state["scope"].unsupported:
            gap = CoverageGap(id="unsupported-" + dimension, kind="unsupported", coordinator=None,
                question=f"Requested dimension {dimension} is not implemented.")
            gaps[gap.id] = gap
        context = synthesis.synthesis_context(state, self.request, records, findings, evidence, gaps)
        remaining = self.resources()
        self.synth.call_limit = self.synth.calls + max(0, remaining["calls"])
        self.synth.token_limit = self.synthesis_token_limit(remaining)
        before = self.synth.calls, self.synth.tokens, self.synth.estimates
        self.resume_synthesis()
        draft = await self.synth.call("synthesize_assessments", {"messages": [], "compact_context": context}, AssessmentSynthesis)
        self.spent = self.spent.model_copy(update={"model_calls": self.spent.model_calls + self.synth.calls - before[0],
            "accounted_tokens": self.spent.accounted_tokens + self.synth.tokens - before[1],
            "estimated_tokens": self.spent.estimated_tokens + self.synth.estimates - before[2]})
        links = [link for link in state["links"] if set(link.finding_refs) <= findings.keys()]
        items = list(findings.items())
        for i, (left_ref, left) in enumerate(items):
            for right_ref, right in items[i + 1:]:
                if left["coordinator"] != right["coordinator"] and ({evidence_key(EvidenceReference.model_validate(e)) for e in left["evidence"]}
                        & {evidence_key(EvidenceReference.model_validate(e)) for e in right["evidence"]}):
                    links.append(AssessmentLink(kind="overlap", finding_refs=[left_ref, right_ref],
                        rationale="These observations share retrieved source ranges; this is shared provenance, not independent confirmation or semantic equivalence."))
        if draft:
            try:
                synthesis.validate_draft(draft, findings, evidence, state["scope"], self.request, self.paths)
            except (ValueError, KeyError):
                draft = None
        if draft:
            for proposal in draft.gaps:
                gid = stable_id("manager-gap", [proposal.kind, proposal.coordinator, proposal.question, sorted(proposal.finding_refs)])
                if gid not in resolved:
                    gaps[gid] = proposal.model_copy(update={"id": gid,
                        "targets": proposal.targets or self.request.dimension_targets.get(proposal.coordinator, self.request.targets)})
            for resolution in draft.resolutions:
                gap = gaps.get(resolution.gap_id)
                record = next((r for r in records if r.assignment.invocation_id == resolution.invocation_id), None)
                if gap and record and record.evidence_sufficient and gap.id in record.assignment.gap_ids:
                    previous = {evidence_key(e) for r in records if r.assignment.round < record.assignment.round for e in r.evidence}
                    if (all(ref.startswith(resolution.invocation_id + "/") and evidence[ref].kind == "source" for ref in resolution.evidence_refs)
                            and any(evidence_key(evidence[ref]) not in previous for ref in resolution.evidence_refs)):
                        gaps.pop(gap.id)
                        resolved.add(gap.id)
            links.extend(draft.links)
        else:
            gaps["manager-synthesis"] = CoverageGap(id="manager-synthesis", kind="synthesis_failure", coordinator=None,
                question="Manager synthesis unavailable or contains invalid references.")
        values = list(gaps.values())
        actionable = [g for g in values if self.actionable(g, records)]
        sufficient = not values and set(covered) == set(state["scope"].assessable) and bool(covered)
        reason = ("coverage_sufficient" if sufficient else "round_limit" if state["rounds_completed"] >= self.config.max_rounds
            else "resource_limit" if not self.can_dispatch(records) else "zero_progress" if not self.progress(state)
            else "no_actionable_follow_up" if not actionable else "targeted_refinement")
        can_follow = reason == "targeted_refinement"
        decision = CoverageDecision(route="no" if can_follow else "yes", sufficient=sufficient, reason=reason,
            covered=covered, required=state["scope"].assessable, actionable_gap_ids=[g.id for g in actionable], can_follow_up=can_follow)
        return {"material_gaps": values, "resolved_gap_ids": sorted(resolved), "actionable_followups": actionable,
            "decision": decision, "summary": synthesis.qualified_summary(draft.summary, findings) if draft else state["summary"],
            "links": list({stable_id("link", link.model_dump()): link for link in links}.values()),
            "synthesis_history": [*state["synthesis_history"], SynthesisRound(round=state["rounds_completed"], draft=draft, decision=decision, gaps=values)]}

    def refine_audit_plan(self, state):
        self.tick("refine_audit_plan")
        grouped = {}
        for gap in state["actionable_followups"]:
            grouped.setdefault(gap.coordinator, []).append(gap)
        pending = []
        for key, gaps in grouped.items():
            targets = list(dict.fromkeys(t for g in gaps for t in g.targets))[:12]
            objective = "\n".join(g.question for g in gaps)
            attempt = 1 + sum(r.assignment.investigator_id == key for r in state["investigation_results"])
            assignment = self.assignment(key, objective, state["rounds_completed"] + 1, targets,
                [g.id for g in gaps], list(dict.fromkeys(ref for g in gaps for ref in g.evidence_refs))[:8], attempt)
            sources = {g.source_assessment_invocation_id for g in gaps if g.source_assessment_invocation_id}
            if sources:
                # Continue one validated cumulative baseline, preserving the full
                # dimension scope rather than promoting a narrow task to coverage.
                source = next(r for r in reversed(state["investigation_results"]) if r.assignment.invocation_id in sources)
                assignment = assignment.model_copy(update={"baseline_invocation_id": source.assignment.invocation_id,
                    "subordinate_gap_ids": list(dict.fromkeys(i for g in gaps for i in g.subordinate_gap_ids)),
                    "targets": source.assignment.targets,
                    "commitments": list({c.model_dump_json(): c for g in gaps for c in g.commitments}.values()),
                    "diagnostics": list(dict.fromkeys(i for g in gaps for i in g.diagnostics))})
            pending.append(assignment)
        return {"pending_assignments": pending, "issued_assignments": [*state["issued_assignments"], *pending]}

    def finalize_audit(self, state):
        self.tick("finalize_audit")
        findings, evidence = self.indexes(state["investigation_results"])
        status = "complete" if state["decision"].sufficient else "partial" if any(r.result and r.status in {"completed", "partial"}
            for r in state["investigation_results"]) else "failed"
        limitations = list(dict.fromkeys([g.question for g in state["material_gaps"]]
            + [w for r in state["investigation_results"] for w in r.warnings] + self.synth.issues + [
                "Only modularity and reusability are implemented; no claim of full ISO/IEC 25010 maintainability coverage.",
                 "Linked observations preserve shared provenance and are not independent confirmation or a numeric quality score."]))
        if state["decision"].reason == "resource_limit":
            remaining = self.resources()
            limits = self.config.invocation_limits
            requirements = [("calls", remaining["calls"], limits.max_model_calls),
                ("tokens", remaining["tokens"], 1 if self.token_budget is not None else limits.max_total_tokens),
                ("tools", remaining["tools"], limits.max_tool_calls),
                ("invocations", self.config.max_invocations - len(state["investigation_results"]), 1),
                ("seconds", self.remaining(), 0.001)]
            limitations.extend(f"resource_shortfall: {key}: disponible={max(0, available):g}; requerido={required:g}"
                for key, available, required in requirements if available < required)
        return {"result": MaintainabilityReport(assessment_id=state["assessment_id"], repository_id=state["repository_id"],
            commit=state["scope"].commit, snapshot_hash=state["snapshot_hash"], objective=self.request.objective, targets=self.request.targets,
            status=status, termination_reason=state["decision"].reason, scope=state["scope"], coverage=state["decision"],
            initial_plan=state["initial_plan"], assessments=state["investigation_results"], findings=findings, evidence=evidence,
            links=[link.model_copy(update={"status": "unresolved" if any(g.kind == "contradiction" and set(g.finding_refs) & set(link.finding_refs)
                for g in state["material_gaps"]) else "resolved"}) if link.kind == "contradiction" else link for link in state["links"]],
            unresolved_gaps=state["material_gaps"], resolved_gap_ids=state["resolved_gap_ids"], summary=state["summary"],
            limitations=limitations, consumption=self.spent, limits=self.config, rounds_completed=state["rounds_completed"],
            duration_seconds=monotonic() - self.started, node_transitions=self.transitions, synthesis_history=state["synthesis_history"],
            ignored_responses=state["ignored_responses"])}

    def build_graph(self):
        builder = StateGraph(MaintainabilityManagerState)
        for name in ("analyze_audit_scope", "plan_audit", "delegate_auditors", "collect_assessments",
                     "synthesize_assessments", "refine_audit_plan", "finalize_audit"):
            builder.add_node(name, getattr(self, name))
        builder.add_edge(START, "analyze_audit_scope")
        builder.add_edge("analyze_audit_scope", "plan_audit")
        builder.add_edge("plan_audit", "delegate_auditors")
        builder.add_edge("delegate_auditors", "collect_assessments")
        builder.add_edge("collect_assessments", "synthesize_assessments")
        builder.add_conditional_edges("synthesize_assessments", coverage_router, {"yes": "finalize_audit", "no": "refine_audit_plan"})
        builder.add_edge("refine_audit_plan", "delegate_auditors")
        builder.add_edge("finalize_audit", END)
        return builder.compile()
