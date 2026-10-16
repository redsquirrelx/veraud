"""Hierarchical maintainability audit with exact bounded coverage-refinement topology."""

import logging
from pathlib import Path
from time import monotonic
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from ....runtimes.coordination.execution import (
    CoordinatorAgent,
    CoordinatorExecution,
    CoordinatorSynthesisExecution,
)
from ....runtimes.coordination.schemas import Consumption
from ....runtimes.coordination.synthesis import evidence_key, stable_id
from ....runtimes.investigation.schemas import EvidenceReference
from ....runtimes.repository.access import repository_relative_path
from ..modularity.coordinator.registry import INVESTIGATORS as MODULARITY_INVESTIGATORS
from ..reusability.coordinator.registry import (
    INVESTIGATORS as REUSABILITY_INVESTIGATORS,
)
from .config import MaintainabilityConfig
from .registry import COORDINATORS
from .schemas import (
    AssessmentLink,
    AssessmentSynthesis,
    AuditAssignment,
    CoordinatorAssessment,
    CoverageDecision,
    CoverageGap,
    MaintainabilityReport,
    MaintainabilityRequest,
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


class MaintainabilityManagerAgent(CoordinatorAgent):
    config_type = MaintainabilityConfig
    trace_name = "maintainability-manager"
    agent_type = "maintainability_manager"

    def __init__(self, model, config=None, *, tracing_backend=None, coordinator_factory=None, provider_pacer=None):
        super().__init__(model, config, tracing_backend=tracing_backend,
            investigator_factory=coordinator_factory, provider_pacer=provider_pacer)

    async def run(self, tools, request=None):
        if tools.budget_usage.tool_calls:
            raise ValueError("Use a fresh RepositoryToolset for the manager.")
        request = MaintainabilityRequest.model_validate(request or MaintainabilityRequest())
        request = request.model_copy(update={"targets": [repository_relative_path(t) for t in request.targets],
            "dimension_targets": {d: [repository_relative_path(t) for t in targets] for d, targets in request.dimension_targets.items()}})
        execution = MaintainabilityManagerExecution(self, tools, request)
        return (await execution.graph.ainvoke(execution.initial_state(),
            {"recursion_limit": 8 * self.config.max_rounds + 16}))["result"]


class MaintainabilityManagerExecution(CoordinatorExecution):
    registry = COORDINATORS
    raw_invocation_type = RawAssessment
    synthesis_execution_type = _ManagerSynthesis

    def tick(self, name):
        name = {"delegate_investigations": "delegate_auditors"}.get(name, name)
        self.transitions.append(name)
        logging.getLogger(__name__).info("maintainability manager node=%s", name)

    def initial_state(self):
        self.audit_id = uuid4().hex
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

    def investigator_request(self, spec, assignment, context):
        context = context[:3500]
        context += f"\nAudit correlation: {self.audit_id}; assignment: {assignment.assignment_id}; attempt: {assignment.invocation_id}."
        context += "\nCoverage criteria: " + "; ".join(assignment.success_criteria)
        context += "\nRequested depth: " + self.request.depth + "; configured resource limits are authoritative."
        args = {"objective": assignment.question, "targets": assignment.targets,
                "architectural_context": context[:6000], "criteria": self.request.criteria}
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
        source = next((f for f in self.tools.accessible_snapshot.files if f.id == ref.file_id), None)
        return bool(source and ref.path == source.path and ref.content_hash == source.content_hash
            and ref.snapshot_hash == self.tools.context.input.snapshot_hash
            and ref.commit in {None, self.tools.accessible_snapshot.repository.commit}
            and (ref.kind != "source" or ref.start_line is not None and ref.end_line is not None
                 and 1 <= ref.start_line <= ref.end_line <= (source.line_count or 0)))

    def validate_result(self, result, assignment):
        snapshot = self.tools.accessible_snapshot.repository
        if (result.repository_id != snapshot.name or result.commit != snapshot.commit or result.snapshot_hash != snapshot.snapshot_hash
                or result.objective != assignment.question or result.targets != assignment.targets):
            raise ValueError("Mismatched coordinator scope/provenance")
        if assignment.investigator_id == "reusability" and result.target_context != self.request.target_context:
            raise ValueError("Mismatched target context")
        usage, budget = result.consumption, assignment.budget
        if budget is None or any(getattr(usage, k) < 0 for k in ("model_calls", "tool_calls", "accounted_tokens", "estimated_tokens")):
            raise ValueError("Invalid accounting")
        if (usage.model_calls > budget.max_model_calls or usage.tool_calls > budget.max_tool_calls
                or usage.accounted_tokens > budget.max_total_tokens or usage.estimated_tokens > usage.accounted_tokens):
            raise ValueError("Usage exceeded reserved envelope")
        if len({r.assignment.invocation_id for r in result.invocations}) != len(result.invocations):
            raise ValueError("Duplicate subordinate invocation IDs")
        if any(sum(getattr(r.consumption, k) for r in result.invocations) > getattr(usage, k)
               for k in ("model_calls", "tool_calls", "accounted_tokens")):
            raise ValueError("Underreported nested usage")
        known = {}
        for record in result.invocations:
            if any(getattr(record.consumption, k) < 0 for k in ("model_calls", "tool_calls", "accounted_tokens", "estimated_tokens")):
                raise ValueError("Invalid nested accounting")
            for ref in record.evidence:
                if not self.valid_reference(ref):
                    raise ValueError("Invalid nested evidence")
                known[(record.assignment.invocation_id, ref.id)] = ref
            if record.result:
                child = record.result
                if (child.snapshot_hash != snapshot.snapshot_hash or child.commit != snapshot.commit
                        or child.repository_id != snapshot.name or child.objective != record.assignment.question):
                    raise ValueError("Invalid nested result provenance")
                for finding in child.findings:
                    for ref in finding.evidence:
                        if known.get((record.assignment.invocation_id, ref.id)) != ref:
                            raise ValueError("Finding not in collected ledger")
                    if finding.validation_status == "accepted":
                        _, mismatch = self.synth.verify_references(finding.evidence)
                        if mismatch or not any(e.kind == "source" for e in finding.evidence):
                            raise ValueError("Unverifiable accepted source attribution")
                def validate_nested(value, invocation_id=record.assignment.invocation_id):
                    if isinstance(value, dict):
                        if {"id", "path", "file_id", "content_hash", "snapshot_hash", "tool_call_id", "kind"} <= value.keys():
                            ref = EvidenceReference.model_validate(value)
                            if not self.valid_reference(ref) or known.get((invocation_id, ref.id)) != ref:
                                raise ValueError("Uncollected nested assessment evidence")
                        for item in value.values():
                            validate_nested(item)
                    elif isinstance(value, list):
                        for item in value:
                            validate_nested(item)
                validate_nested(child.model_dump())
        for group in result.consolidated_findings:
            for contribution in group.contributions:
                record = next((r for r in result.invocations if r.assignment.invocation_id == contribution.invocation_id), None)
                if (not record or not record.result or contribution.investigator_id != record.assignment.investigator_id
                        or contribution.reference != f"{contribution.invocation_id}/{contribution.finding.id}"
                        or not any(f == contribution.finding and f.validation_status == "accepted" for f in record.result.findings)):
                    raise ValueError("Unsupported consolidated contribution")
            available = {evidence_key(e) for c in group.contributions for e in c.finding.evidence}
            if any(evidence_key(e) not in available or not self.valid_reference(e) for e in group.evidence):
                raise ValueError("Unsupported consolidated evidence")

    def coverage_issues(self, result, key):
        issues = []
        if result.status != "completed" or result.material_gaps:
            issues.append("Coordinator incomplete or material gaps unresolved.")
        registry = MODULARITY_INVESTIGATORS if key == "modularity" else REUSABILITY_INVESTIGATORS
        if {a.investigator_id for a in result.initial_plan} != set(registry):
            issues.append("Coordinator initial plan does not cover its registered investigator lenses.")
        for investigator in registry:
            if not any(r.assignment.investigator_id == investigator and r.status == "completed" and r.result and r.result.plan
                       and getattr(r.result, "status", "completed") == "completed" and not r.result.missing_information
                       and not any(h.status in {"pending", "inconclusive"} for h in r.result.hypotheses)
                       and any(e.kind == "source" for e in r.evidence) for r in result.invocations):
                issues.append(f"No completed planned source-backed investigation from {investigator}.")
        if any(g.status == "disputed" for g in result.consolidated_findings):
            issues.append("Disputed subordinate finding remains.")
        return issues

    def collect_assessments(self, state):
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
            usage = Consumption()
            if assignment.budget:
                usage = Consumption(model_calls=assignment.budget.max_model_calls, tool_calls=assignment.budget.max_tool_calls,
                    accounted_tokens=assignment.budget.max_total_tokens, estimated_tokens=assignment.budget.max_total_tokens,
                    model_calls_estimated=True)
            status, error, result, issues = raw.status, raw.error, None, []
            if status == "received":
                try:
                    value = raw.value.model_dump() if hasattr(raw.value, "model_dump") else raw.value
                    result = self.registry[assignment.investigator_id].result_class.model_validate(value)
                    self.validate_result(result, assignment)
                    usage = result.consumption
                    issues = self.coverage_issues(result, assignment.investigator_id)
                    status = "completed" if not issues else "failed" if result.status == "failed" else "partial"
                except Exception as exc:  # noqa: BLE001 - untrusted subordinate boundary
                    result, status, error = None, "failed", type(exc).__name__
            evidence = [e for r in result.invocations for e in r.evidence] if result else []
            record = CoordinatorAssessment(assignment=assignment, result=result, status=status, error=error,
                evidence=evidence, consumption=usage, duration_seconds=raw.duration_seconds,
                warnings=result.limitations if result else [], coverage_issues=issues, evidence_sufficient=status == "completed")
            records.append(record)
            self.spent = Consumption(**{k: getattr(self.spent, k) + getattr(usage, k)
                for k in ("model_calls", "tool_calls", "accounted_tokens", "estimated_tokens")},
                model_calls_estimated=self.spent.model_calls_estimated or usage.model_calls_estimated)
        return {"investigation_results": records,
                "rounds_completed": state["rounds_completed"] + int(len(records) > len(state["investigation_results"])),
                "ignored_responses": ignored}

    @staticmethod
    def indexes(records):
        findings, evidence = {}, {}
        for record in records:
            if record.result:
                prefix = record.assignment.invocation_id + "/"
                for invocation in record.result.invocations:
                    for ref in invocation.evidence:
                        evidence[prefix + invocation.assignment.invocation_id + "/" + ref.id] = ref
                for group in record.result.consolidated_findings:
                    findings[prefix + group.id] = {"coordinator": record.assignment.investigator_id,
                        "invocation_id": record.assignment.invocation_id, **group.model_dump(mode="json")}
        return findings, evidence

    def actionable(self, gap, records):
        if not gap.blocking or gap.coordinator is None:
            return False
        calls = [r for r in records if r.assignment.investigator_id == gap.coordinator]
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
                or any(r.evidence_sufficient and not any(p.evidence_sufficient and p.assignment.investigator_id == r.assignment.investigator_id
                       for p in prior) for r in latest))

    async def synthesize_assessments(self, state):
        self.tick("synthesize_assessments")
        records = state["investigation_results"]
        findings, evidence = self.indexes(records)
        covered = [d for d in state["scope"].assessable if any(r.assignment.investigator_id == d and r.evidence_sufficient for r in records)]
        gaps = {g.id: g for g in state["material_gaps"] if g.kind not in {"missing_coverage", "synthesis_failure"}}
        for dimension in state["scope"].assessable:
            if dimension not in covered:
                calls = [r for r in records if r.assignment.investigator_id == dimension]
                details = "; ".join(calls[-1].coverage_issues) if calls else "No result"
                gap = CoverageGap(id="coverage-" + dimension, kind="missing_coverage", coordinator=dimension,
                    question=f"Complete the missing source-backed {dimension} coverage. {details}",
                    targets=self.request.dimension_targets.get(dimension, self.request.targets))
                gaps[gap.id] = gap
        for dimension in state["scope"].unsupported:
            gap = CoverageGap(id="unsupported-" + dimension, kind="unsupported", coordinator=None,
                question=f"Requested dimension {dimension} is not implemented.")
            gaps[gap.id] = gap
        compact_findings = {ref: {"coordinator": value["coordinator"], "concern": value["concern"], "status": value["status"],
            "affected_components": value["affected_components"], "limitations": value["limitations"],
            "contributions": [{"reference": c["reference"], "investigator_id": c["investigator_id"],
                "classification": c["finding"].get("classification"), "category": c["finding"].get("category"),
                "assumptions": c["finding"].get("assumptions", []), "assessed_context": c["finding"].get("assessed_context"),
                "evidence_refs": [value["invocation_id"] + "/" + c["invocation_id"] + "/" + e["id"]
                    for e in c["finding"]["evidence"] if e["kind"] == "source"]} for c in value["contributions"]]}
            for ref, value in findings.items()}
        context = {"audit_id": state["assessment_id"], "objective": self.request.objective, "scope": state["scope"].model_dump(),
            "assessments": [{"invocation_id": r.assignment.invocation_id, "coordinator": r.assignment.investigator_id,
                "status": r.status, "coverage_issues": r.coverage_issues, "gap_ids": r.assignment.gap_ids,
                "summary": r.result.summary if r.result else "", "limitations": r.warnings[:8]} for r in records],
            "findings": compact_findings, "evidence": {k: v.model_dump() for k, v in evidence.items() if v.kind == "source"},
            "gaps": [g.model_dump() for g in gaps.values()]}
        remaining = self.resources()
        self.synth.call_limit = self.synth.calls + max(0, remaining["calls"])
        self.synth.token_limit = self.synth.tokens + max(0, remaining["tokens"])
        before = self.synth.calls, self.synth.tokens, self.synth.estimates
        draft = await self.synth.call("synthesize_assessments", {"messages": [], "compact_context": context}, AssessmentSynthesis)
        self.spent = self.spent.model_copy(update={"model_calls": self.spent.model_calls + self.synth.calls - before[0],
            "accounted_tokens": self.spent.accounted_tokens + self.synth.tokens - before[1],
            "estimated_tokens": self.spent.estimated_tokens + self.synth.estimates - before[2]})
        resolved = set(state["resolved_gap_ids"])
        links = list(state["links"])
        items = list(findings.items())
        for i, (left_ref, left) in enumerate(items):
            for right_ref, right in items[i + 1:]:
                if left["coordinator"] != right["coordinator"] and ({evidence_key(EvidenceReference.model_validate(e)) for e in left["evidence"]}
                        & {evidence_key(EvidenceReference.model_validate(e)) for e in right["evidence"]}):
                    links.append(AssessmentLink(kind="overlap", finding_refs=[left_ref, right_ref],
                        rationale="These observations share retrieved source ranges; this is shared provenance, not independent confirmation or semantic equivalence."))
        if draft:
            try:
                for link in draft.links:
                    if len(set(link.finding_refs)) < 2 or not set(link.finding_refs) <= findings.keys():
                        raise ValueError("Unknown finding reference")
                for gap in draft.gaps:
                    if (gap.kind not in {"quality", "contradiction"} or gap.coordinator not in state["scope"].assessable
                            or not gap.blocking or not gap.question.strip() or not set(gap.finding_refs) <= findings.keys()
                            or not set(gap.evidence_refs) <= evidence.keys()):
                        raise ValueError("Invalid proposed gap")
                    for target in gap.targets:
                        target = repository_relative_path(target)
                        scope_targets = self.request.dimension_targets.get(gap.coordinator, self.request.targets)
                        if (target not in self.paths and not any(p.startswith(target + "/") for p in self.paths)
                                or scope_targets and not any(target == t or target.startswith(t + "/") for t in scope_targets)):
                            raise ValueError("Inaccessible gap target")
                for link in draft.links:
                    if link.kind == "contradiction" and not any(g.kind == "contradiction" and set(link.finding_refs) <= set(g.finding_refs) for g in draft.gaps):
                        raise ValueError("Untracked contradiction")
                for resolution in draft.resolutions:
                    if not set(resolution.evidence_refs) <= evidence.keys():
                        raise ValueError("Unknown resolution evidence")
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
            "decision": decision, "summary": draft.summary if draft else state["summary"],
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
            pending.append(self.assignment(key, objective, state["rounds_completed"] + 1, targets,
                [g.id for g in gaps], list(dict.fromkeys(ref for g in gaps for ref in g.evidence_refs))[:8], attempt))
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
