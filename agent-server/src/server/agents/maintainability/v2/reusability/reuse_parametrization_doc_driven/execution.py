"""Plan plus iterative reuse-parametrization investigation; synthesis/finalize are not implemented yet."""

import sys
from pathlib import Path

from langgraph.graph import END, START, StateGraph
from pydantic_core import PydanticCustomError

from server.contracts.audit import Hypothesis
from server.runtimes.investigation.agent import InvestigationExecution
from server.runtimes.invocation_reporting import phase_node

from .investigation import ParametrizationInvestigation
from .planning import build_parametrization_plan
from .schemas import (
    ParametrizationPlan,
    ParametrizationPlanSelection,
    ReuseParametrizationDocDrivenResult,
)
from .state import ParametrizationState


class ReuseParametrizationDocDrivenExecution(ParametrizationInvestigation, InvestigationExecution):
    trace_name = "reuse-parametrization-doc-driven"
    tool_prefix = "reuse-parametrization"
    prompt_directory = Path(__file__).parent / "prompts"
    plan_schema = ParametrizationPlan
    result_schema = ReuseParametrizationDocDrivenResult

    def _check_planning(self):
        self.timing.check_cancellation()
        if self.remaining_seconds() <= 0:
            raise TimeoutError("Reuse-parametrization planning deadline exhausted.")

    def initial_state(self):
        snapshot = self.tools.accessible_snapshot
        return super().initial_state() | {
            "snapshot_hash": snapshot.repository.snapshot_hash,
            "current_investigation": 0,
            "pending_queries": [],
            "active_query_keys": [],
            "query_cache": {},
            "initial_evidence_loaded": False,
            "coverage_recovery_done": False,
            "task_limitations": [],
            "investigation_results": [],
        }

    def _build_graph(self):
        graph = StateGraph(ParametrizationState)
        graph.add_node("plan_investigation", phase_node("plan_investigation", self.plan_investigation))
        graph.add_node("investigate", phase_node("investigate", self.investigate))
        graph.add_node("tools", phase_node("tools", self.execute_investigation_tools))
        graph.add_edge(START, "plan_investigation")
        graph.add_edge("plan_investigation", "investigate")
        graph.add_conditional_edges("investigate", self.route_investigation,
            {"tools": "tools", "investigate": "investigate", "end": END})
        graph.add_edge("tools", "investigate")
        return graph.compile()

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
            return self._validate_turn(result, state)
        return super().prepare_structured_result(node, result, state)

    async def provider_request(self, model, messages, overhead, node, schema, reserved_calls):
        if node == "investigate":
            instruction = (
                "Return the requested JSON, not native tool calls. To investigate an unresolved question, "
                "return action=tools with focused queries; the graph executes them and returns their evidence "
                "for your next decision. Close directly when the existing evidence suffices."
            )
            messages = [message.model_copy(update={"content": instruction})
                if message.type == "human" and message.content == "Now execute investigate. Return the requested JSON, no tools."
                else message for message in messages]
        response = await super().provider_request(model, messages, overhead, node, schema, reserved_calls)
        if response is not None:
            raw = response.get("raw") if isinstance(response, dict) else response
            print(f"[DEBUG_LLM_RAW {node}] {getattr(raw, 'content', raw)}", file=sys.stderr)
        return response

    # --- plan -------------------------------------------------------------

    async def plan_investigation(self, state):
        limitations_note = (
            "Model selection of deterministic candidates; no violations or findings are established. "
            "The model only ranks existing menu IDs; empty slots are not refilled automatically.")
        menu_limit = min(32, max(self.config.max_planned_investigations * 2, self.config.max_planned_investigations))
        try:
            menu_plan = build_parametrization_plan(self.tools.accessible_snapshot, self.request,
                check=self._check_planning, max_investigations=menu_limit,
                max_documentary_claims_per_candidate=self.config.max_documentary_claims_per_candidate)
        except TimeoutError:
            self.stop = "time_limit"
            menu_plan = ParametrizationPlan(objectives=[self.request.objective], components=[], hypotheses=[],
                candidates=[], limitations=[limitations_note, "Planning time allowance exhausted."], document_claims={})
        self._menu = list(menu_plan.candidates)
        self._menu_claims = dict(menu_plan.document_claims)
        print(f"[DEBUG_PLAN_MENU] candidates={len(self._menu)}", file=sys.stderr)
        for item in self._menu:
            mechanism = (item.variation_mechanism or "")[:100]
            print(f"[DEBUG_PLAN_MENU_CANDIDATE] id={item.id} mechanism={mechanism} basis={item.variation_basis} "
                f"priority={item.priority} primary={item.primary_component}",
                file=sys.stderr)
        self._planning_context = {
            "objective": self.request.objective,
            "constraints": self.request.constraints,
            "criteria": [item.model_dump() for item in self.request.criteria],
            "targets": self.request.targets,
            "budget": {"max_investigations": self.config.max_planned_investigations},
            "candidates": [{"id": item.id, "priority": item.priority,
                "primary_component": item.primary_component,
                "symbol_name": item.symbol_name,
                "symbol_kind": item.symbol_kind,
                "variation_mechanism": item.variation_mechanism,
                "variation_basis": item.variation_basis,
                "alternatives": item.alternatives,
                "documented_capability": item.documented_capability,
                "observed_indicators": item.observed_indicators,
                "claims": [{"id": claim_id,
                    "subject": self._menu_claims[claim_id].claim.subject,
                    "statement": self._menu_claims[claim_id].claim.statement,
                    "constraint": self._menu_claims[claim_id].claim.constraint,
                    "certainty": self._menu_claims[claim_id].claim.certainty}
                    for claim_id in item.document_claim_ids
                    if claim_id in self._menu_claims]} for item in self._menu],
            "limitations": menu_plan.limitations,
        }
        selection = await self.call("plan_investigation", state, ParametrizationPlanSelection) if self._menu else None
        selected_ids = list(selection.candidate_ids) if selection else []
        print(f"[DEBUG_PLAN_SELECTION] selected={selected_ids}", file=sys.stderr)
        by_id = {item.id: item for item in self._menu}
        final = [by_id[key].model_copy(update={
            "question": selection.questions[key] if selection.questions.get(key)
            else by_id[key].question})
            if selection else by_id[key] for key in selection.candidate_ids] if selection is not None else []
        limitations = list(menu_plan.limitations)
        if selection is None and self._menu:
            limitations.append("Model planning did not finish; no candidate was selected.")
        limitations.append(f"Planning menu diagnostics: shown={len(self._menu)}, selected={len(final)}, discarded={max(0, len(self._menu) - len(final))}.")
        plan = ParametrizationPlan(
            objectives=[self.request.objective],
            components=list(dict.fromkeys(path for item in final for path in item.scope)),
            hypotheses=[Hypothesis(id=item.id, question=item.question,
                criterion_id="parametrized-reuse", priority=item.priority,
                evidence_needed=item.evidence_needed) for item in final],
            candidates=final, limitations=list(dict.fromkeys(limitations)),
            document_claims={key: self._menu_claims[key] for item in final for key in item.document_claim_ids
                if key in self._menu_claims})
        if not final and self._menu and selection is not None:
            limitations.append("The model abstained from the supplied menu.")
            plan = plan.model_copy(update={"limitations": list(dict.fromkeys(limitations))})
        diagnostics = {
            "executed_plan_stages": ["plan_investigation"],
            "documentary_context_supplied": self.request.documented_architecture is not None,
            "menu_shown": len(self._menu),
            "selected": len(final),
            "discarded": max(0, len(self._menu) - len(final)),
            "llm_calls": 1 if selection is not None else 0,
            "planning": "deterministic menu, model selection; grounded by host; no source investigation or findings",
        }
        reason = self.stop or "planning_completed"
        result = self.result_schema(
            repository_id=state["repository_id"],
            commit=state["commit"],
            snapshot_hash=self.tools.context.input.snapshot_hash,
            objective=state["objective"],
            plan=plan,
            findings=[],
            hypotheses=plan.hypotheses,
            investigation_results=[],
            missing_information=[],
            limitations=plan.limitations,
            termination_reason=reason,
            model_calls=self.calls,
            tool_calls=self.tools.budget_usage.tool_calls,
            iterations=0,
            accounted_tokens=self.tokens,
            estimated_tokens=self.estimates,
            evidence=self.references(),
            status="planning_only",
            planning_diagnostics=diagnostics,
        )
        return {
            "plan": plan,
            "result": result,
            "hypotheses": plan.hypotheses,
            "model_calls": self.calls,
            "tool_calls": self.tools.budget_usage.tool_calls,
            "termination_reason": result.termination_reason,
            "missing_information": [],
            "limitations": result.limitations,
        }
