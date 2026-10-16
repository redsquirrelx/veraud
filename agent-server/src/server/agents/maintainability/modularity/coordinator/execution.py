"""Modularity bindings and graph over the domain-independent coordinator runtime."""

from itertools import pairwise
from pathlib import Path
from time import monotonic

from langgraph.graph import END, START, StateGraph

from .....runtimes.coordination.execution import (
    CoordinatorExecution,
    CoordinatorSynthesisExecution,
)
from .....runtimes.coordination.synthesis import request_key
from .registry import INVESTIGATORS
from .schemas import (
    Assignment,
    EvidenceGap,
    InvocationRecord,
    ModularityAssessment,
    RawInvocation,
    SynthesisDraft,
)
from .state import ModularityState
from .synthesis import actionable, consolidate, detect_contradictions, finding_index


def route_after_synthesis(state):
    """Explicit, state-only router; the model cannot override limits."""
    if not state["material_gaps"]:
        return "finalize"
    if not state["actionable_followups"]:
        return "finalize_limited" if any(g.kind == "essential_failure" for g in state["material_gaps"]) else "finalize"
    if state["rounds_completed"] >= state["max_rounds"] or not state["budgets"]["can_dispatch"]:
        return "finalize_limited"
    return "reinvestigate"


class ModularitySynthesisExecution(CoordinatorSynthesisExecution):
    prompt_directory = Path(__file__).parent / "prompts"


class ModularityExecution(CoordinatorExecution):
    registry = INVESTIGATORS
    assignment_type = Assignment
    raw_invocation_type = RawInvocation
    invocation_record_type = InvocationRecord
    gap_type = EvidenceGap
    synthesis_draft_type = SynthesisDraft
    synthesis_execution_type = ModularitySynthesisExecution
    finding_index = staticmethod(finding_index)
    detect_contradictions = staticmethod(detect_contradictions)
    consolidate = staticmethod(consolidate)
    actionable = staticmethod(actionable)

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
