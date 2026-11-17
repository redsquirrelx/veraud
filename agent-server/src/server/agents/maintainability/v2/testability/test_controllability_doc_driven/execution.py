"""Plan plus iterative investigate."""

import json
from pathlib import Path

from langgraph.graph import END, START, StateGraph
from pydantic_core import PydanticCustomError

from server.contracts.audit import Hypothesis
from server.runtimes.investigation.agent import InvestigationExecution
from server.runtimes.invocation_reporting import phase_node

from .investigation import TestControllabilityInvestigation
from .planning import build_test_controllability_plan
from .schemas import (
    TestControllabilityFinding,
    TestControllabilityPlan,
    TestControllabilityPlanSelection,
    TestControllabilityResult,
)
from .state import TestControllabilityState
from .synthesis import consolidate_candidates, synthesize_documentary


class TestControllabilityExecution(TestControllabilityInvestigation, InvestigationExecution):
    trace_name = "test_controllability"
    tool_prefix = "test_controllability"
    prompt_directory = Path(__file__).parent / "prompts"
    plan_schema = TestControllabilityPlan
    finding_schema = TestControllabilityFinding
    result_schema = TestControllabilityResult

    def _check_planning(self):
        self.timing.check_cancellation()
        if self.remaining_seconds() <= 0:
            raise TimeoutError("test-controllability planning deadline exhausted.")

    def model_context(self, node, state):
        if node == "plan_investigation":
            return self._planning_context
        if node == "investigate":
            return self._investigation_context(state)
        return super().model_context(node, state)

    def prepare_structured_result(self, node, result, state):
        if node == "plan_investigation":
            allowed = {item.id for item in self._menu}
            if len(result.candidate_ids) > self.config.max_planned_investigations:
                raise PydanticCustomError("planning_size_limit", "Respect budget.max_investigations.")
            if len(set(result.candidate_ids)) != len(result.candidate_ids) or set(result.candidate_ids) - allowed:
                raise PydanticCustomError("planning_unknown_candidate", "Select unique candidate_ids from the menu only.")
            by_id = {item.id: item for item in self._menu}
            if set(result.questions) - set(result.candidate_ids):
                raise PydanticCustomError("planning_unknown_candidate", "Questions must reference selected candidate_ids only.")
            for key, question in result.questions.items():
                primary = by_id[key].primary_component
                if not question or not question.strip() or primary.lower() not in question.lower():
                    raise PydanticCustomError("planning_invalid_question", "Each question must name its primary component.")
            return result
        if node == "investigate":
            result = self._repair_conclusion(result, state)
            self._validate_turn(result, state)
        return result

    def _repair_conclusion(self, turn, state):
        """Mechanical consistency repair, applied before validation.

        Never invents or alters semantics: identifiers come only from what the
        model already produced plus host-delivered evidence. Adds missing
        delivered evidence references to candidate/conclusion lists (additive),
        drops references that cannot exist (subset operations), and never
        creates claims, assessments or candidates.
        """
        conclusion = turn.conclusion
        if turn.action != "close" or conclusion is None:
            return turn
        task = self._current(state)
        delivered = self._delivered_ids(state)
        own_ids = set(conclusion.evidence_ids)
        assessment_ids = {identifier for item in conclusion.claim_assessments for identifier in item.code_evidence_ids}
        candidate_ids = {identifier for candidate in conclusion.candidates for identifier in candidate.evidence_ids}
        # Additive linkage: delivered evidence the model already produced belongs
        # in the shared ledger of the conclusion.
        linked = sorted((delivered & (assessment_ids | candidate_ids)) | own_ids)
        conclusion = conclusion.model_copy(update={"evidence_ids": list(dict.fromkeys([*conclusion.evidence_ids, *linked]))[:80]})
        source_paths = {record.path for record in self.references()
            if record.kind == "source" and record.id in delivered}
        assessments = [item.model_copy(update={
            "code_evidence_ids": [identifier for identifier in item.code_evidence_ids if identifier in delivered],
            "scope_paths": [path for path in item.scope_paths if path in source_paths],
        }) for item in conclusion.claim_assessments]
        conclusion = conclusion.model_copy(update={"claim_assessments": assessments})
        contradicted = {item.claim_id: item for item in conclusion.claim_assessments if item.status == "contradicted"}
        candidates = [candidate.model_copy(update={
            # A candidate may cite only contradicted claims; drop the rest.
            "document_claim_ids": [key for key in dict.fromkeys(candidate.document_claim_ids) if key in contradicted],
            "evidence_ids": [identifier for identifier in candidate.evidence_ids if identifier in delivered],
        }) for candidate in conclusion.candidates]
        # Mechanical claim↔candidate linkage for finding_candidate: every
        # contradicted claim the conclusion contains must be engaged by some
        # candidate. The model's assessments already produced the evidence
        # ids; the host only attaches the claim to the candidate that shares
        # the most assessment evidence, or to the first candidate when there
        # is no overlap signal. No claim is created or evaluated.
        if conclusion.status == "finding_candidate" and candidates:
            cited = {key for candidate in candidates for key in candidate.document_claim_ids}
            for key in sorted(set(contradicted) - cited):
                anchors = contradicted[key].code_evidence_ids
                best = max(range(len(candidates)),
                    key=lambda position: len(set(candidates[position].evidence_ids) & set(anchors)))
                target = candidates[best]
                candidates[best] = target.model_copy(update={
                    "document_claim_ids": [*target.document_claim_ids, key]})
        candidates = [candidate.model_copy(update={
            "evidence_ids": list(dict.fromkeys([*candidate.evidence_ids, *(
                {identifier for key in candidate.document_claim_ids
                    if key in contradicted for identifier in contradicted[key].code_evidence_ids
                    if identifier in delivered})]))})
            for candidate in candidates]
        allowed_claims = set(task.document_claim_ids)
        candidates = [candidate.model_copy(update={
            "document_claim_ids": [key for key in dict.fromkeys(candidate.document_claim_ids) if key in allowed_claims]})
            for candidate in candidates]
        examined = set(self._examined_relationships(state))
        visible_symbols = {symbol for record in self.references() if record.id in set(conclusion.evidence_ids)
            for symbol in record.symbol_ids}
        candidates = [candidate.model_copy(update={
            "symbol_ids": [symbol for symbol in candidate.symbol_ids if symbol in visible_symbols],
            "relationship_ids": [relationship for relationship in candidate.relationship_ids if relationship in examined]})
            for candidate in candidates]
        conclusion = conclusion.model_copy(update={
            "candidates": candidates,
            "symbol_ids": [symbol for symbol in conclusion.symbol_ids if symbol in visible_symbols],
            "relationship_ids": [relationship for relationship in conclusion.relationship_ids if relationship in examined],
        })
        return turn.model_copy(update={"conclusion": conclusion})

    async def provider_request(self, model, messages, overhead, node, schema, reserved_calls):
        if node == "investigate":
            instruction = ("Return the requested JSON, not native tool calls. To investigate an unresolved question, "
                "return action=tools with focused queries; the graph executes them and returns their evidence "
                "for your next decision. Close directly when the existing evidence suffices.")
            messages = [message.model_copy(update={"content": instruction})
                if message.type == "human" and message.content == "Now execute investigate. Return the requested JSON, no tools." else message for message in messages]
        return await super().provider_request(model, messages, overhead, node, schema, reserved_calls)

    # --- plan -------------------------------------------------------------

    async def plan_investigation(self, state):
        limitations_note = (
            "Model selection of deterministic candidates; no violations or findings are established. "
            "The model only ranks existing menu IDs; empty slots are not refilled automatically.")
        menu_limit = min(32, max(self.config.max_planned_investigations * 2, self.config.max_planned_investigations))
        try:
            menu_plan = build_test_controllability_plan(self.tools.accessible_snapshot, self.request,
                check=self._check_planning, max_investigations=menu_limit,
                max_documentary_claims_per_candidate=self.config.max_documentary_claims_per_candidate)
        except TimeoutError:
            self.stop = "time_limit"
            menu_plan = TestControllabilityPlan(objectives=[self.request.objective], components=[], hypotheses=[],
                candidates=[], limitations=[limitations_note, "Planning time allowance exhausted."])
        self._menu = list(menu_plan.candidates)
        self._menu_claims = dict(menu_plan.document_claims)
        self._planning_context = {
            "objective": self.request.objective,
            "constraints": self.request.constraints,
            "criteria": [item.model_dump() for item in self.request.criteria],
            "targets": self.request.targets,
            "budget": {"max_investigations": self.config.max_planned_investigations},
            "candidates": [{"id": item.id, "priority": item.priority,
                "primary_component": item.primary_component,
                "collaborators": item.collaborators,
                "documented_control_contract": item.documented_control_contract,
                "observed_indicators": item.observed_indicators,
                "evidence_needed": item.evidence_needed,
                "control_category": item.control_category} for item in self._menu],
            "limitations": menu_plan.limitations,
        }
        selection = await self.call("plan_investigation", state, TestControllabilityPlanSelection) if self._menu else None
        by_id = {item.id: item for item in self._menu}
        final = [by_id[key].model_copy(update={"question": selection.questions[key] if selection.questions.get(key) else by_id[key].question})
            if selection else by_id[key] for key in selection.candidate_ids] if selection is not None else []
        limitations = list(menu_plan.limitations)
        if selection is None and self._menu:
            limitations.append("Model planning did not finish; no candidate was selected.")
        limitations.append(f"Planning menu diagnostics: shown={len(self._menu)}, selected={len(final)}, discarded={max(0, len(self._menu) - len(final))}.")
        plan = TestControllabilityPlan(
            objectives=[self.request.objective],
            components=list(dict.fromkeys(path for item in final for path in item.scope)),
            hypotheses=[Hypothesis(id=item.id, question=item.question,
                criterion_id="test-controllability", priority=item.priority,
                evidence_needed=item.evidence_needed) for item in final],
            candidates=final, limitations=list(dict.fromkeys(limitations)),
            document_claims={key: self._menu_claims[key] for item in final for key in item.document_claim_ids
                if key in self._menu_claims})
        if not final and self._menu and selection is not None:
            limitations.append("The model abstained from the supplied menu.")
            plan = plan.model_copy(update={"limitations": list(dict.fromkeys(limitations))})
        reason = self.stop or "planning_completed"
        result = self.result_schema(
            repository_id=state["repository_id"], commit=state["commit"],
            snapshot_hash=self.tools.context.input.snapshot_hash,
            objective=state["objective"], plan=plan, findings=[], hypotheses=plan.hypotheses,
            missing_information=[], limitations=plan.limitations,
            termination_reason=reason, model_calls=self.calls,
            tool_calls=self.tools.budget_usage.tool_calls, iterations=0,
            accounted_tokens=self.tokens, estimated_tokens=self.estimates,
            deferred_stages=self.deferred_stages, evidence=self.references())
        return {"plan": plan, "result": result, "hypotheses": plan.hypotheses, "model_calls": self.calls,
            "tool_calls": self.tools.budget_usage.tool_calls,
            "termination_reason": result.termination_reason,
            "missing_information": [], "limitations": result.limitations}

    # --- investigate graph ------------------------------------------------

    def _build_graph(self):
        graph = StateGraph(TestControllabilityState)
        graph.add_node("plan_investigation", phase_node("plan_investigation", self.plan_investigation))
        graph.add_node("investigate", phase_node("investigate", self.investigate))
        graph.add_node("tools", phase_node("tools", self.execute_investigation_tools))
        graph.add_node("synthesis", phase_node("synthesis", self.synthesis))
        graph.add_node("finalize", phase_node("finalize", self.finalize))
        graph.add_edge(START, "plan_investigation")
        graph.add_edge("plan_investigation", "investigate")
        graph.add_conditional_edges("investigate", self.route_investigation,
            {"tools": "tools", "investigate": "investigate", "synthesis": "synthesis"})
        graph.add_edge("tools", "investigate")
        graph.add_edge("synthesis", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile()

    def synthesis(self, state):
        candidates, origins = consolidate_candidates(state["investigation_results"])
        synthesis = synthesize_documentary(state["investigation_results"], state["plan"],
            state["result"].evidence, getattr(self.tools.context.input, "snapshot_hash", None))
        self.logger.info("test_controllability_synthesis %s", json.dumps({
            "original_candidates": sum(len(item.candidates) for item in state["investigation_results"]),
            "consolidated_candidates": len(candidates),
            "documentary_claims_evaluated": len(synthesis.coverage.evaluated_claim_ids),
            "documentary_integrity_issues": len(synthesis.integrity_issues)}, sort_keys=True))
        result = state["result"].model_copy(update={"candidates": candidates,
            "candidate_origins": origins, "documentary_synthesis": synthesis,
            "termination_reason": state["result"].termination_reason})
        return {"candidates": candidates, "candidate_origins": origins,
            "documentary_synthesis": synthesis, "result": result}

    def finalize(self, state):
        ledger, _mismatch = self.verify_references(self.references())
        references = {reference.id: reference for reference in ledger}
        criteria = {criterion.id: criterion for criterion in self.request.criteria}
        findings = []
        for candidate in state["candidates"]:
            criterion = criteria.get(candidate.criterion_id)
            if criterion is None:
                continue
            findings.append(TestControllabilityFinding(
                **candidate.model_dump(exclude={"symbol_ids", "relationship_ids",
                    "observed_mechanisms", "substitution_blockers"}),
                criterion=criterion,
                evidence=[references[identifier] for identifier in candidate.evidence_ids if identifier in references],
                validation_status="insufficient_evidence",
                review_rationale="No critical review performed; consolidated provisional candidate."))
        limitations = list(dict.fromkeys([*state["limitations"], *self.issues,
            *(f"Documentary synthesis {issue.code}: {issue.message}" for issue in
                getattr(state.get("documentary_synthesis"), "integrity_issues", [])),
            *(limitation for item in state["investigation_results"] for limitation in item.limitations)]))
        missing = [f"Investigation {item.investigation_id}: {limitation}"
            for item in state["investigation_results"] if item.status == "inconclusive" for limitation in item.limitations]
        result = state["result"].model_copy(update={"findings": findings,
            "missing_information": missing, "limitations": limitations,
            "model_calls": self.calls, "tool_calls": self.tools.budget_usage.tool_calls,
            "accounted_tokens": self.tokens, "estimated_tokens": self.estimates,
            "evidence": ledger, "termination_reason": state["termination_reason"]})
        return {"result": result, "evidence": ledger, "missing_information": missing, "limitations": limitations}

    def initial_state(self):
        return super().initial_state() | {"current_investigation": 0, "investigation_results": [],
            "pending_queries": [], "query_cache": {}, "active_query_keys": [],
            "initial_evidence_loaded": False, "task_limitations": [],
            "candidates": [], "candidate_origins": {}, "documentary_synthesis": None}
