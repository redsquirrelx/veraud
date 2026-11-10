"""Graph shell with bounded planning and abstraction investigate/tools implemented."""

import re
import sys
from pathlib import Path

from langgraph.graph import END, START, StateGraph
from pydantic_core import PydanticCustomError

from server.contracts.audit import Hypothesis
from server.runtimes.investigation.agent import InvestigationExecution
from server.runtimes.invocation_reporting import phase_node

from .investigation import AbstractionInvestigation
from .planning import build_abstraction_plan
from .schemas import (
    AbstractionFinding,
    AbstractionPlan,
    AbstractionPlanSelection,
    AbstractionResult,
)
from .state import AbstractionState
from .synthesis import consolidate_candidates, documentary_coverage


class AbstractionExecution(AbstractionInvestigation, InvestigationExecution):
    trace_name = "abstraction-v2-investigator"
    tool_prefix = "abstraction"
    prompt_directory = Path(__file__).parent / "prompts"
    plan_schema = AbstractionPlan
    result_schema = AbstractionResult

    def _check_planning(self):
        self.timing.check_cancellation()
        if self.remaining_seconds() <= 0:
            raise TimeoutError("Abstraction planning deadline exhausted.")

    @staticmethod
    def _obligation_anchor_audit(text, candidate):
        haystack = re.sub(r"[^a-z0-9]", "", text.casefold())
        claims = [claim_id for claim_id in (candidate.document_claim_ids or [])
            if (re.sub(r"[^a-z0-9]", "", str(claim_id).casefold()) in haystack)
                and re.sub(r"[^a-z0-9]", "", str(claim_id).casefold())]
        paths = []
        for path in [candidate.primary_component, *(candidate.related_components or [])]:
            normalized = re.sub(r"[^a-z0-9]", "", str(path).casefold()) if path else ""
            if normalized and normalized in haystack:
                paths.append(path)
        anchored = bool(claims or paths) or bool(
            re.sub(r"[^a-z0-9]", "", candidate.abstraction_name.casefold()) in haystack)
        compound = len(claims) > 1 or len(paths) > 1
        return anchored, compound, len(claims), len(paths)

    def _obligation_requirements(self, selection):
        """Obligation-derived requirements: the only evidence_needed that ships."""
        requirements = getattr(selection, "evidence_requirements", None) or {}
        selected = set(selection.candidate_ids)
        unknown = sorted(set(requirements) - selected)
        if unknown:
            raise PydanticCustomError("planning_requirements_unknown_candidate",
                f"Obligation requirements are attached to unselected candidate_ids: {', '.join(unknown)}.")
        menu = {item.id: item for item in self._menu}
        cleaned = {}
        for key in selected:
            candidate = menu[key]
            items = requirements.get(key, [])
            output, seen = [], set()
            for index, item in enumerate(items):
                text = re.sub(r"\s+", " ", str(item)).strip()
                text = re.sub(r"^[*\-•\d.)]+\s*", "", text).strip()
                if not (12 <= len(text) <= 400):
                    raise PydanticCustomError("planning_requirements_invalid",
                        f"Candidate {key}: evidence requirement {index + 1} must be a checkable statement of 12-400 characters.")
                anchored, compound, claim_count, path_count = self._obligation_anchor_audit(text, candidate)
                if compound:
                    raise PydanticCustomError("planning_requirements_compound",
                        f"Candidate {key}: evidence requirement {index + 1} bundles {claim_count} claim(s) and "
                        f"{path_count} related component(s); keep one claim and/or one component per requirement.")
                if not anchored:
                    raise PydanticCustomError("planning_requirements_invalid",
                        f"Candidate {key}: evidence requirement {index + 1} must name the abstraction, its primary "
                        f"component, a related component or a claim_id.")
                if text.casefold() in seen:
                    continue
                seen.add(text.casefold())
                output.append(text)
            if not (2 <= len(output) <= 5):
                raise PydanticCustomError("planning_requirements_invalid",
                    f"Candidate {key}: every selected candidate needs 2-5 obligation-derived requirements.")
            cleaned[key] = output
        return cleaned

    async def provider_request(self, model, messages, overhead, node, schema, reserved_calls):
        if node == "investigate":
            instruction = ("Return the requested JSON, not native tool calls. To investigate an unresolved question, "
                "return action=tools with focused queries; the graph executes them and returns their evidence "
                "for your next decision. Close directly when the existing evidence suffices.")
            messages = [message.model_copy(update={"content": instruction})
                if message.type == "human" and message.content == "Now execute investigate. Return the requested JSON, no tools." else message for message in messages]
        response = await super().provider_request(model, messages, overhead, node, schema, reserved_calls)
        if response is not None:
            raw = response.get("raw") if isinstance(response, dict) else response
            print(f"[DEBUG_LLM_RAW {node}] {getattr(raw, 'content', raw)}", file=sys.stderr)
        return response

    def model_context(self, node, state):
        if node == "plan_investigation":
            return self._planning_context
        if node == "investigate":
            return self._investigation_context(state)
        return super().model_context(node, state)

    def structured_correction_context(self, node, state):
        if node == "investigate":
            task = self._current(state)
            references = [record for record in self.references()
                if record.id in self._delivered_ids(state)]
            inspected = {record.path for record in references if record.kind == "source"}
            delivered_ids = {record.id for record in references if record.kind == "source"}
            requirements = getattr(self, "_resolution_failed_requirements", set())
            return {"inspected_paths": sorted(inspected),
                "scope_paths_must_be_inspected": sorted(inspected),
                "uninspected_related_paths": sorted(set(task.related_components) - inspected),
                "claims_to_assess": task.document_claim_ids,
                "pending_requirement_indexes": sorted(requirements),
                "delivered_source_ids": sorted(delivered_ids),
                "evidence_requirements": list(enumerate(task.evidence_needed)),
                "delivered_source": [{"id": record.id, "path": record.path,
                    "start_line": record.start_line, "end_line": record.end_line}
                    for record in references if record.kind == "source"],
                "closure_error": getattr(self, "_closure_error", None)}
        return super().structured_correction_context(node, state)

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
            self._obligation_addenda = self._obligation_requirements(result)
            return result
        if node == "investigate":
            result = self._normalize_investigate_result(result)
            result = self._repair_reference_fields(result, state)
            result = self._normalize_investigate_result(result)
            try:
                self._validate_turn(result, state)
            except PydanticCustomError as error:
                self._closure_error = {"code": error.type}
                self._resolution_failed_requirements = self._unresolved_requirement_indexes(result, state)
                raise
            self._closure_error = None
            self._resolution_failed_requirements = set()
        return result

    def _unresolved_requirement_indexes(self, result, state):
        conclusion = getattr(result, "conclusion", None)
        if conclusion is None:
            return set()
        assessments = list(getattr(conclusion, "evidence_assessments", []) or [])
        current = {item.requirement_index for item in assessments}
        required = set(range(len(state["plan"].candidates[state["current_investigation"]].evidence_needed)))
        return required - current | {item.requirement_index for item in assessments
            if getattr(item, "status", None) == "inconclusive"}

    def _repair_reference_fields(self, result, state):
        """Drop model citations that are not grounded in deliverable artifacts.

        Preserve the model's close; discarded citations are reported through
        subject limitations, never silently.
        """
        conclusion = getattr(result, "conclusion", None)
        if conclusion is None:
            return result
        references = {record.id: record for record in self.references() if record.id in self._delivered_ids(state)}
        symbols = {symbol.id: symbol for symbol in self.tools.accessible_snapshot.symbols}
        examined = set(self._examined_relationships(state))

        def repair(subject):
            source_cited = [record for record in (references.get(identifier) for identifier in subject.evidence_ids)
                if record is not None and record.kind == "source"]
            kept_symbols, dropped_symbols = [], []
            for identifier in subject.symbol_ids:
                symbol = symbols.get(identifier)
                if symbol is not None and any(record.kind == "source" and record.file_id == symbol.file_id
                        and record.start_line is not None and record.start_line <= symbol.end_line
                        and record.end_line is not None and record.end_line >= symbol.start_line
                        for record in source_cited):
                    kept_symbols.append(identifier)
                else:
                    dropped_symbols.append(identifier)
            kept_relationships, dropped_relationships = [], []
            for identifier in subject.relationship_ids:
                (kept_relationships if identifier in examined else dropped_relationships).append(identifier)
            notes = []
            if dropped_relationships:
                notes.append("relationship_ids not derived from list_relationships: " + ", ".join(sorted(dropped_relationships)))
            if dropped_symbols:
                notes.append("symbol_ids not grounded in delivered source: " + ", ".join(sorted(dropped_symbols)))
            if not notes:
                return subject
            return subject.model_copy(update={
                "relationship_ids": kept_relationships, "symbol_ids": kept_symbols,
                "limitations": [*subject.limitations,
                    "Model evidence citations removed during validation: " + "; ".join(notes) + "."]})

        candidates = [repair(candidate) for candidate in conclusion.candidates]
        head = repair(conclusion.model_copy(update={"candidates": candidates}))
        relationship_ids = list(dict.fromkeys([*head.relationship_ids,
            *(identifier for candidate in candidates for identifier in candidate.relationship_ids)]))
        symbol_ids = list(dict.fromkeys([*head.symbol_ids,
            *(identifier for candidate in candidates for identifier in candidate.symbol_ids)]))
        return result.model_copy(update={"conclusion": head.model_copy(update={
            "candidates": candidates,
            "relationship_ids": relationship_ids, "symbol_ids": symbol_ids})})

    @staticmethod
    def _normalize_investigate_result(result):
        conclusion = getattr(result, "conclusion", None)
        if conclusion is None:
            return result
        evidence, relationships = list(conclusion.evidence_ids), list(conclusion.relationship_ids)
        for candidate in conclusion.candidates:
            evidence += candidate.evidence_ids
            relationships += candidate.relationship_ids
        for assessment in conclusion.claim_assessments:
            evidence += assessment.code_evidence_ids
        for assessment in conclusion.evidence_assessments:
            evidence += assessment.evidence_ids
        return result.model_copy(update={"conclusion": conclusion.model_copy(update={
            "evidence_ids": list(dict.fromkeys(evidence)),
            "relationship_ids": list(dict.fromkeys(relationships))})})

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
            "candidates": [],
            "candidate_origins": {},
            "documentary_synthesis": {},
            "synthesis": {},
        }

    # --- plan -------------------------------------------------------------

    async def plan_investigation(self, state):
        limitations_note = (
            "Model selection of deterministic candidates; no violations or findings are established. "
            "The model only ranks existing menu IDs; empty slots are not refilled automatically.")
        menu_limit = min(32, max(2 * self.config.max_planned_investigations, self.config.max_planned_investigations))
        try:
            menu_plan = build_abstraction_plan(self.tools.accessible_snapshot, self.request,
                check=self._check_planning, max_investigations=menu_limit)
        except TimeoutError:
            self.stop = "time_limit"
            menu_plan = AbstractionPlan(objectives=[self.request.objective], components=[], hypotheses=[],
                candidates=[], limitations=[limitations_note, "Planning time allowance exhausted."], document_claims={})
        self._obligation_addenda = {}
        self._menu = list(menu_plan.candidates)
        self._menu_claims = dict(menu_plan.document_claims)
        print(f"[DEBUG_PLAN_MENU] candidates={len(self._menu)}", file=sys.stderr)
        for item in self._menu:
            purpose = (item.documented_purpose or "").replace("\n", " ")[:100]
            print(f"[DEBUG_PLAN_MENU_CANDIDATE] id={item.id} abstraction={item.abstraction_name} kind={item.abstraction_kind} "
                f"basis={item.purpose_basis} priority={item.priority} primary={item.primary_component} purpose={purpose!r}",
                file=sys.stderr)
        self._planning_context = {
            "objective": self.request.objective,
            "constraints": self.request.constraints,
            "criteria": [item.model_dump() for item in self.request.criteria],
            "targets": self.request.targets,
            "budget": {"max_investigations": self.config.max_planned_investigations},
            "candidates": [{"id": item.id, "priority": item.priority,
                "primary_component": item.primary_component,
                "abstraction_name": item.abstraction_name,
                "abstraction_kind": item.abstraction_kind,
                "related_components": item.related_components,
                "documented_purpose": item.documented_purpose,
                "purpose_basis": item.purpose_basis,
                "observed_indicators": item.observed_indicators,
                "claims": [{"id": claim_id,
                    "subject": self._menu_claims[claim_id].subject,
                    "statement": self._menu_claims[claim_id].statement,
                    "constraint": self._menu_claims[claim_id].constraint,
                    "certainty": self._menu_claims[claim_id].certainty}
                    for claim_id in item.document_claim_ids
                    if claim_id in self._menu_claims],
                "document_claim_ids": item.document_claim_ids} for item in self._menu],
            "limitations": menu_plan.limitations,
        }
        selection = await self.call("plan_investigation", state, AbstractionPlanSelection) if self._menu else None
        selected_ids = list(selection.candidate_ids) if selection else []
        discarded_names = [item.abstraction_name for item in self._menu if item.id not in selected_ids]
        print(f"[DEBUG_PLAN_SELECTION] selected={selected_ids} discarded={discarded_names}", file=sys.stderr)
        by_id = {item.id: item for item in self._menu}
        requirements = getattr(self, "_obligation_addenda", {})
        final = [by_id[key].model_copy(update={
            "question": selection.questions[key] if selection.questions.get(key)
            else by_id[key].question,
            "evidence_needed": requirements[key]})
            if selection else by_id[key] for key in selection.candidate_ids] if selection is not None else []
        limitations = list(menu_plan.limitations)
        if selection is None and self._menu:
            limitations.append("Model planning did not finish; no candidate was selected.")
        limitations.append(f"Planning menu diagnostics: shown={len(self._menu)}, selected={len(final)}, discarded={max(0, len(self._menu) - len(final))}.")
        requirements_added = sum(len(items) for items in requirements.values())
        if requirements_added:
            limitations.append(f"Obligation-derived evidence requirements (replacing generic baselines): {requirements_added} across {len(requirements)} selected candidate(s).")
        plan = AbstractionPlan(
            objectives=[self.request.objective],
            components=list(dict.fromkeys(path for item in final for path in item.scope)),
            hypotheses=[Hypothesis(id=item.id, question=item.question,
                criterion_id="abstraction-purpose", priority=item.priority,
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
            investigation_results=[],
            missing_information=[], limitations=plan.limitations,
            termination_reason=reason, model_calls=self.calls,
            tool_calls=self.tools.budget_usage.tool_calls, iterations=0,
            accounted_tokens=self.tokens, estimated_tokens=self.estimates,
            deferred_stages=self.deferred_stages, evidence=self.references())
        return {"plan": plan, "result": result, "hypotheses": plan.hypotheses, "model_calls": self.calls,
            "tool_calls": self.tools.budget_usage.tool_calls,
            "termination_reason": result.termination_reason,
            "missing_information": [], "limitations": result.limitations}

    def synthesis(self, state):
        candidates, origins = consolidate_candidates(state["investigation_results"])
        synthesis = documentary_coverage(state["investigation_results"], state["plan"])
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
            findings.append(AbstractionFinding(
                **candidate.model_dump(exclude={"symbol_ids", "relationship_ids", "guarantees", "implementers", "consumers"}),
                criterion=criterion,
                evidence=[references[identifier] for identifier in candidate.evidence_ids if identifier in references],
                validation_status="insufficient_evidence",
                review_rationale="No critical review performed; consolidated provisional candidate."))
        limitations = list(dict.fromkeys([*state["limitations"], *self.issues,
            *(limitation for item in state["investigation_results"] for limitation in item.limitations)]))
        missing = [f"Investigation {item.investigation_id}: {limitation}"
            for item in state["investigation_results"] if item.status == "inconclusive" for limitation in item.limitations]
        result = state["result"].model_copy(update={"findings": findings,
            "missing_information": missing, "limitations": limitations,
            "model_calls": self.calls, "tool_calls": self.tools.budget_usage.tool_calls,
            "accounted_tokens": self.tokens, "estimated_tokens": self.estimates,
            "evidence": ledger, "termination_reason": state["termination_reason"]})
        return {"result": result, "evidence": ledger, "missing_information": missing, "limitations": limitations}

    # --- investigate graph --------------------------------------------------

    def route_after_plan(self, state):
        plan = state.get("plan")
        return "investigate" if plan is not None and plan.candidates else "end"

    def _build_graph(self):
        graph = StateGraph(AbstractionState)
        graph.add_node("plan_investigation", phase_node("plan_investigation", self.plan_investigation))
        graph.add_node("investigate", phase_node("investigate", self.investigate))
        graph.add_node("tools", phase_node("tools", self.execute_investigation_tools))
        graph.add_node("synthesize", phase_node("synthesize", self.synthesis))
        graph.add_node("finalize", phase_node("finalize", self.finalize))
        graph.add_edge(START, "plan_investigation")
        graph.add_conditional_edges("plan_investigation", self.route_after_plan,
            {"investigate": "investigate", "end": END})
        graph.add_conditional_edges("investigate", self.route_investigation,
            {"tools": "tools", "investigate": "investigate", "synthesis": "synthesize"})
        graph.add_edge("tools", "investigate")
        graph.add_edge("synthesize", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile()

    @staticmethod
    def _not_implemented(name):
        def missing(*_args, **_kwargs):
            raise NotImplementedError(f"Abstraction node {name!r} has not been implemented yet.")
        return missing
