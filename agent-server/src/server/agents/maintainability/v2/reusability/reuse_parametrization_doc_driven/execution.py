"""Plan plus iterative reuse-parametrization investigation; synthesis/finalize are not implemented yet."""

import sys
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from server.runtimes.investigation.agent import InvestigationExecution
from server.runtimes.invocation_reporting import phase_node

from .investigation import ParametrizationInvestigation
from .planning import (
    _claim_batch_context,
    _consolidation_context,
    _memory_from_responses,
    _structural_provisional,
    build_parametrization_plan,
    build_parametrization_planning,
)
from .schemas import (
    ParametrizationConsolidationResponse,
    ParametrizationPlanningResponse,
    ReuseParametrizationDocDrivenResult,
)
from .state import ParametrizationState


class ReuseParametrizationDocDrivenExecution(ParametrizationInvestigation, InvestigationExecution):
    trace_name = "reuse-parametrization-doc-driven"
    tool_prefix = "reuse-parametrization"
    prompt_directory = Path(__file__).parent / "prompts"
    plan_schema = None
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
        if node == "consolidate":
            return self._consolidation_context
        if node == "investigate":
            return self._investigation_context(state)
        return super().model_context(node, state)

    def prepare_structured_result(self, node, result, state):
        if node == "investigate":
            result = self._validate_turn(result, state)
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

    async def plan_investigation(self, state):
        limitations_note = (
            "Claim batches were sent to semantic discovery; no implementation, finding or hypothesis of viability is established."
            " The model proposes investigation questions only; host grounds and merges those proposals."
        )
        try:
            batch_limit = max(8_000, int(self.config.max_context_characters * 0.6))
            planning = build_parametrization_planning(
                self.tools.accessible_snapshot,
                self.request,
                check=self._check_planning,
                max_investigations=self.config.max_planned_investigations,
                batch_limit=batch_limit,
            )
        except TimeoutError:
            self.stop = "time_limit"
            planning = {
                "snapshot_hash": self.tools.context.input.snapshot_hash,
                "claims": [],
                "batches": [],
                "consumers_by_path": {},
                "symbols_by_file": {},
                "files": {},
                "code_references": [],
                "max_investigations": self.config.max_planned_investigations,
                "limitations": [limitations_note, "Planning time allowance exhausted."],
                "objective": self.request.objective,
            }

        responses: list[ParametrizationPlanningResponse | None] = []
        for index, batch in enumerate(planning["batches"]):
            prior_candidates = _memory_from_responses(planning, responses) if responses else []
            self._planning_context = _claim_batch_context(
                planning, self.request, batch, index, len(planning["batches"]), prior_candidates)
            print(
                f"[DEBUG_PLAN_BATCH] batch={index + 1}/{len(planning['batches'])} claims={len(batch)} "
                f"references={len(self._planning_context['code_references'])} prior_candidates={len(prior_candidates)}",
                file=sys.stderr,
            )
            response = await self.call("plan_investigation", state, ParametrizationPlanningResponse)
            responses.append(response)
            if response is None:
                print(f"[DEBUG_PLAN_RESPONSE] batch={index + 1} unavailable", file=sys.stderr)
            else:
                print(
                    f"[DEBUG_PLAN_RESPONSE] batch={index + 1} candidates={len(response.candidates)} "
                    f"exclusions={len(response.exclusions)} limitations={len(response.limitations)}",
                    file=sys.stderr,
                )

        if planning["batches"]:
            print(
                f"[DEBUG_PLAN_RESPONSES] batches={len(responses)} responses={sum(response is not None for response in responses)}",
                file=sys.stderr,
            )
        provisional, _structural_failures, _structural_rejected = _structural_provisional(planning, responses)
        print(f"[DEBUG_PLAN_PROVISIONAL] accepted={len(provisional)} rejected={_structural_rejected}", file=sys.stderr)
        if provisional:
            consolidation_context = _consolidation_context(planning, provisional)
            self._consolidation_context = consolidation_context
            consolidation_response = await self.call("consolidate", state, ParametrizationConsolidationResponse)
        else:
            consolidation_response = None
        plan = build_parametrization_plan(planning, consolidation_response, provisional)
        print(
            f"[DEBUG_PLAN_ACCEPTED] proposed={sum(len(response.candidates) for response in responses if response is not None)} "
            f"consolidated={len(consolidation_response.candidates) if consolidation_response is not None else 0} "
            f"accepted={len(plan.candidates)}",
            file=sys.stderr,
        )
        for item in plan.candidates:
            print(
                f"[DEBUG_PLAN_CANDIDATE] id={item.id} primary={item.primary_component} "
                f"mechanism={item.variation_mechanism} basis={item.variation_basis} "
                f"priority={item.priority} claim_ids={item.document_claim_ids}",
                file=sys.stderr,
            )

        batch_count = len(planning["batches"])
        candidates_proposed = sum(len(response.candidates) for response in responses if response is not None)
        consolidation_candidates = len(consolidation_response.candidates) if consolidation_response is not None else 0
        model_excluded = sum(len(response.exclusions) for response in responses if response is not None) + (
            len(consolidation_response.exclusions) if consolidation_response is not None else 0)
        if model_excluded:
            plan = plan.model_copy(update={"limitations": list(dict.fromkeys([
                *plan.limitations,
                f"Exclusion diagnostics: the model rejected {model_excluded} plausible option(s).",
            ]))})
        diagnostics = {
            "executed_plan_stages": ["plan_investigation"],
            "documentary_context_supplied": self.request.documented_architecture is not None,
            "claims_sent_to_model": sum(len(batch) for batch in planning["batches"]),
            "references_sent_to_model": len(planning["code_references"]) * batch_count,
            "claim_batches": batch_count,
            "provisional_candidates": len(provisional),
            "provisional_rejected": _structural_rejected,
            "proposed": candidates_proposed,
            "accepted": len(plan.candidates),
            "host_rejected": _structural_rejected + max(0, consolidation_candidates - len(plan.candidates)),
            "model_excluded": model_excluded,
            "llm_calls": sum(response is not None for response in responses) + (
                1 if consolidation_response is not None else 0),
            "planning": "semantic discovery by batches, global semantic consolidation, grounded by host; no source investigation or findings",
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
