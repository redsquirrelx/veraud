"""Exact five-node coordination graph plus a deterministic conditional decision."""

from time import monotonic
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from .....runtimes.coordination.execution import (
    CoordinatorExecution,
)
from .....runtimes.coordination.synthesis import (
    evidence_key,
    request_key,
    semantic_key,
    stable_id,
)
from .....runtimes.investigation.schemas import EvidenceReference
from . import synthesis
from .registry import EVIDENCE_EXPECTATIONS, INVESTIGATORS
from .schemas import (
    Assignment,
    ContinuationDecision,
    EvidenceGap,
    InvocationRecord,
    RawInvocation,
    ReusabilityAssessment,
    Route,
    SynthesisDraft,
    SynthesisRound,
)
from .state import ReusabilityState


def route_after_synthesis(state) -> Route:
    """State-only guard; the model cannot dispatch, override budgets or add nodes."""
    decision = state["continuation_decision"]
    return Route.YES if (decision.route == Route.YES and state["material_gaps"]
        and state["pending_assignments"] and state["actionable_followups"]
        and state["rounds_completed"] < state["max_rounds"] and state["budgets"]["can_dispatch"]) else Route.NO


class ReusabilityExecution(CoordinatorExecution):
    registry = INVESTIGATORS
    assignment_type = Assignment
    raw_invocation_type = RawInvocation
    invocation_record_type = InvocationRecord
    gap_type = EvidenceGap
    synthesis_draft_type = SynthesisDraft
    synthesis_execution_type = synthesis.ReusabilitySynthesisExecution
    finding_index = staticmethod(synthesis.finding_index)
    detect_contradictions = staticmethod(synthesis.detect_contradictions)
    consolidate = staticmethod(synthesis.consolidate)
    actionable = staticmethod(synthesis.actionable)

    def initial_state(self):
        state = super().initial_state()
        self.assessment_id = state["assessment_id"]
        state.update(synthesis_history=[], continuation_decision=ContinuationDecision(route=Route.NO,
            reason="not_synthesized", material_gap_ids=[], pending_request_ids=[]))
        return state

    def assignment(self, investigator, question, round_number, targets, refs=None, gaps=None):
        return Assignment(invocation_id=uuid4().hex, request_id=uuid4().hex,
            round_id=stable_id("round", [self.assessment_id, round_number]), investigator_id=investigator,
            round=round_number, question=question, targets=targets, evidence_refs=refs or [], gap_ids=gaps or [],
            evidence_expectations=EVIDENCE_EXPECTATIONS[investigator])

    def configure_investigator(self, investigator):
        if hasattr(investigator, "provider_pacer"):
            investigator.provider_pacer = self.provider_pacer

    def investigator_request(self, spec, assignment, context):
        context += "\nEvidence expectations: " + "; ".join(assignment.evidence_expectations)
        args = {"objective": assignment.question, "architectural_context": context, "targets": assignment.targets}
        if self.request.criteria:
            args["criteria"] = self.request.criteria
        if assignment.investigator_id == "component_adaptability":
            args["target_context"] = self.request.target_context
        return spec.request_class(**args)

    def invocation_metadata(self, assignment, state):
        return {**super().invocation_metadata(assignment, state), "name": "reusability-investigation",
                "assessment_id": state["assessment_id"], "request_id": assignment.request_id, "round_id": assignment.round_id}

    def valid_reference(self, ref):
        files = {f.id: f for f in self.tools.accessible_snapshot.files}
        source = files.get(ref.file_id)
        return bool(source and ref.path == source.path and ref.content_hash == source.content_hash
            and ref.snapshot_hash == self.tools.context.input.snapshot_hash
            and (ref.kind != "source" or ref.start_line is not None and ref.end_line is not None
                 and 1 <= ref.start_line <= ref.end_line <= (source.line_count or 0)))

    def validate_collected_result(self, result, raw, state):
        snapshot = self.tools.accessible_snapshot
        if (result.snapshot_hash != state["snapshot_hash"] or result.commit != snapshot.repository.commit
                or result.repository_id != snapshot.repository.name or result.objective != raw.assignment.question):
            raise ValueError("Mismatched repository provenance")
        budget = raw.assignment.budget
        if budget is None or any(n < 0 for n in [result.model_calls, result.tool_calls, result.accounted_tokens, result.estimated_tokens]):
            raise ValueError("Invalid usage accounting")
        if (result.model_calls > budget.max_model_calls or result.tool_calls > budget.max_tool_calls
                or result.accounted_tokens > budget.max_total_tokens or result.estimated_tokens > result.accounted_tokens):
            raise ValueError("Reported usage exceeded reservation")
        if raw.assignment.investigator_id == "component_adaptability" and result.target_context != self.request.target_context:
            raise ValueError("Mismatched target context")
        ledger = {e.id: e for e in raw.evidence}

        def inspect(value):
            if isinstance(value, dict):
                if {"id", "path", "snapshot_hash", "content_hash", "kind", "tool_call_id", "file_id"} <= value.keys():
                    ref = EvidenceReference.model_validate(value)
                    actual = ledger.get(ref.id)
                    if (not actual or not self.valid_reference(ref)
                            or ref.model_dump(exclude={"commit"}) != actual.model_dump(exclude={"commit"})
                            or ref.commit not in {None, result.commit}):
                        raise ValueError("Evidence did not resolve to inspected ledger")
                for child in value.values():
                    inspect(child)
            elif isinstance(value, list):
                for child in value:
                    inspect(child)
        inspect(result.model_dump())
        for finding in result.findings:
            if set(finding.evidence_ids) != {e.id for e in finding.evidence}:
                raise ValueError("Finding citations did not match inspected evidence")
            if finding.validation_status == "accepted":
                _, mismatch = self.synth.verify_references(finding.evidence)
                if mismatch or not any(e.kind == "source" for e in finding.evidence) or any(e.commit != result.commit for e in finding.evidence):
                    raise ValueError("Accepted finding has unverifiable source attribution")

    def result_status(self, result):
        if result.status == "failed":
            return "failed"
        if result.status != "completed" or getattr(result, "tool_failures", []):
            return "partial"
        coverage = result.coverage
        if coverage and any(getattr(coverage, key, []) for key in ("unassessed_candidates", "unassessed_groups", "unassessed_components")):
            return "partial"
        examined = (getattr(result, "abstractions_investigated", []) + getattr(result, "examined_groups", [])
                    + getattr(result, "examined_constraints", []))
        if any(item.validation_status != "source_backed" or item.validation_issues
               or getattr(item, "conclusion", None) in {"unknown", "inconclusive"} for item in examined):
            return "partial"
        return super().result_status(result)

    def collect_findings(self, state):
        update = super().collect_findings(state)
        # Invalid returned schemas cannot supply claims, but actual tool observations
        # from a failed/timed-out invocation remain useful, namespaced provenance.
        raw = {r.assignment.invocation_id: r for r in state["execution_records"]}
        records = []
        for record in update["investigation_results"]:
            item = raw.get(record.assignment.invocation_id)
            if item and record.result is None:
                record = record.model_copy(update={"evidence": [e for e in item.evidence if self.valid_reference(e)]})
            unique = list({(e.id, e.tool_call_id): e for e in record.evidence}.values())
            verified, _ = self.synth.verify_references(unique)
            record = record.model_copy(update={"evidence": verified})
            records.append(record)
        update["investigation_results"] = records
        return update

    def synthesis_context(self, context, state, records):
        index = self.finding_index(records)
        for ref, contribution in index.items():
            context["findings"][ref].update(investigator_id=contribution.investigator_id,
                polarity=synthesis.polarity(contribution.finding),
                details=contribution.finding.model_dump(exclude={"evidence", "criterion"}))
        rounds = {r.assignment.invocation_id: r.assignment.round for r in records}
        for invocation in context["invocations"]:
            invocation["round"] = rounds[invocation["invocation_id"]]
        return context | {"target_context": self.request.target_context,
            "coverage": [{"invocation_id": r.assignment.invocation_id,
                "coverage": r.result.coverage.model_dump() if r.result and r.result.coverage else None,
                "investigation_status": r.result.status if r.result else None} for r in records]}

    def made_progress(self, state, update):
        if state["rounds_completed"] <= 1:
            return True
        records = state["investigation_results"]
        latest = [r for r in records if r.assignment.round == state["rounds_completed"]]
        prior = [r for r in records if r.assignment.round < state["rounds_completed"]]
        known = {evidence_key(e) for r in prior for e in r.evidence if e.kind == "source"}
        if any(e.kind == "source" and evidence_key(e) not in known for r in latest for e in r.evidence):
            return True
        if set(update["resolved_gap_ids"]) - set(state["resolved_gap_ids"]):
            return True
        signatures = {(semantic_key(c.finding), c.finding.validation_status, getattr(c.finding, "classification", None),
                       getattr(c.finding, "category", None)) for c in self.finding_index(prior).values()}
        return any((semantic_key(c.finding), c.finding.validation_status, getattr(c.finding, "classification", None),
                    getattr(c.finding, "category", None)) not in signatures for c in self.finding_index(latest).values())

    async def synthesize_findings(self, state):
        update = await super().synthesize_findings(state)
        gaps = update["material_gaps"]
        followups = update["actionable_followups"]
        reason = ("sufficient_evidence" if not gaps else
                  "round_limit" if state["rounds_completed"] >= self.config.max_rounds else
                  "resource_limit" if not update["budgets"]["can_dispatch"] else
                  "zero_progress" if not self.made_progress(state, update) else
                  "no_useful_follow_up" if not followups else "targeted_follow_up")
        pending = []
        if reason == "targeted_follow_up":
            grouped = {}
            for gap in followups:
                grouped.setdefault(request_key(gap.investigator_id, gap.question, gap.targets), []).append(gap)
            for group in list(grouped.values())[:len(self.registry)]:
                first = group[0]
                pending.append(self.assignment(first.investigator_id, first.question, state["rounds_completed"] + 1,
                    first.targets, list(dict.fromkeys(ref for g in group for ref in g.evidence_refs))[:8], [g.id for g in group]))
        decision = ContinuationDecision(route=Route.YES if pending else Route.NO, reason=reason,
            rationale=("Targeted material questions: " + "; ".join(g.question for g in followups)) if pending else
                      f"No further dispatch ({reason}); {len(gaps)} material question(s) remain.",
            material_gap_ids=[g.id for g in gaps], pending_request_ids=[a.request_id for a in pending])
        self.synth.logger.info("reusability decision=%s reason=%s pending=%s", decision.route, reason, len(pending))
        history = [*state["synthesis_history"], SynthesisRound(round=state["rounds_completed"], draft=self.synth.last_draft, decision=decision)]
        return {**update, "pending_assignments": pending, "continuation_decision": decision,
                "termination_reason": reason, "synthesis_history": history}

    def finalize_assessment(self, state):
        self.tick("finalize_assessment")
        records = state["investigation_results"]
        usable = any(r.result is not None and r.status in {"completed", "partial"} for r in records)
        status = "completed" if not state["material_gaps"] and usable else "partial" if usable else "failed"
        withdrawn = set(state["withdrawn_finding_refs"])
        findings = self.finding_index(records)
        conclusions, relationships = {}, {}
        for item in state["synthesis_history"]:
            if item.draft:
                for conclusion in item.draft.conclusions:
                    if all(r in findings and r not in withdrawn and findings[r].finding.validation_status == "accepted" for r in conclusion.finding_refs):
                        disputed = any(g.kind == "contradiction" and set(g.finding_refs) & set(conclusion.finding_refs) for g in state["material_gaps"])
                        conclusion = conclusion.model_copy(update={"status": "disputed" if disputed else "supported"})
                        conclusions[stable_id("conclusion", conclusion.model_dump())] = conclusion
                for relationship in item.draft.relationships:
                    if relationship.kind == "conflicts":
                        unresolved = any(g.kind == "contradiction" and set(g.finding_refs) & set(relationship.finding_refs) for g in state["material_gaps"])
                        relationship = relationship.model_copy(update={"resolution_status": "unresolved" if unresolved else "resolved"})
                    relationships[stable_id("relationship", [relationship.kind, sorted(relationship.finding_refs)])] = relationship
        limitations = list(dict.fromkeys([g.question for g in state["material_gaps"]]
            + [w for r in records for w in r.warnings] + self.synth.issues + [
                "Coordination preserves investigator evidence and judgments; it does not independently prove semantic equivalence, portability or global coverage."]))
        coverage = {key: [{"invocation_id": r.assignment.invocation_id, "round": r.assignment.round,
            "status": r.status, "coverage": r.result.coverage.model_dump() if r.result and r.result.coverage else None}
            for r in records if r.assignment.investigator_id == key] for key in self.registry}
        return {"result": ReusabilityAssessment(assessment_id=state["assessment_id"], repository_id=state["repository_id"],
            commit=self.tools.accessible_snapshot.repository.commit, snapshot_hash=state["snapshot_hash"], objective=self.request.objective,
            targets=self.request.targets, target_context=self.request.target_context, status=status,
            termination_reason=state["termination_reason"], summary=state["summary"], investigator_registry=state["investigator_registry"],
            initial_plan=state["initial_plan"], invocations=records, consolidated_findings=state["consolidated_findings"],
            material_gaps=state["material_gaps"], resolved_gap_ids=state["resolved_gap_ids"], withdrawn_finding_refs=state["withdrawn_finding_refs"],
            conclusions=list(conclusions.values()), finding_relationships=list(relationships.values()), synthesis_history=state["synthesis_history"],
            continuation_decision=state["continuation_decision"], limitations=limitations, rounds_completed=state["rounds_completed"],
            consumption=self.spent, duration_seconds=monotonic() - self.started, node_transitions=self.transitions, coverage=coverage)}

    def build_graph(self):
        graph = StateGraph(ReusabilityState)
        for name in ("plan_assessment", "delegate_investigations", "collect_findings", "synthesize_findings", "finalize_assessment"):
            graph.add_node(name, getattr(self, name))
        graph.add_edge(START, "plan_assessment")
        graph.add_edge("plan_assessment", "delegate_investigations")
        graph.add_edge("delegate_investigations", "collect_findings")
        graph.add_edge("collect_findings", "synthesize_findings")
        graph.add_conditional_edges("synthesize_findings", route_after_synthesis,
            {Route.YES: "delegate_investigations", Route.NO: "finalize_assessment"})
        graph.add_edge("finalize_assessment", END)
        return graph.compile()
