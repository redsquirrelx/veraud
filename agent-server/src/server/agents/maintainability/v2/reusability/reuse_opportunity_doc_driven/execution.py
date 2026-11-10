"""LLM discovery, global correlation and evidence-backed formulation in one node."""

import json
import sys
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic_core import PydanticCustomError

from server.contracts.audit import Hypothesis
from server.runtimes.investigation.agent import InvestigationExecution
from server.runtimes.invocation_reporting import phase_node
from server.runtimes.repository.access import (
    RepositoryAccessError,
    repository_relative_path,
)
from server.services.repository_analysis.context import create_identifier

from .investigation import ReuseInvestigation as ReuseInvestigationMixin
from .planning import (
    complementary_claims,
    discovery_projection,
    documentary_records,
    relevant_paths,
)
from .schemas import (
    ReuseCorrelationResponse,
    ReuseDiscoveryResponse,
    ReuseInvestigation,
    ReuseInvestigationTurn,
    ReuseOpportunityDocDrivenResult,
    ReuseOpportunityPlan,
    ReusePlanningResponse,
)
from .state import ReuseOpportunityState


class ReuseOpportunityExecution(ReuseInvestigationMixin, InvestigationExecution):
    trace_name = "reuse-opportunity-doc-driven-v2-investigator"
    tool_prefix = "reuse_opportunity_doc_driven"
    prompt_directory = Path(__file__).parent / "prompts"
    result_schema = ReuseOpportunityDocDrivenResult

    async def provider_request(self, model, messages, overhead, node, schema, reserved_calls):
        # planning keeps its own validation diagnostics; investigation gets a
        # concise reminder because native tool calls are not accepted there.
        if node == "investigate":
            instruction = ("Return the requested JSON, not native tool calls. To inspect "
                           "an unresolved question, return action=tools with focused queries; "
                           "the graph executes them and returns their evidence for your next decision. "
                           "Close directly when the evidence suffices or inconclusive is honestly supported.")
            messages = [message.model_copy(update={"content": instruction})
                if message.type == "human" and message.content == "Now execute investigate. Return the requested JSON, no tools."
                else message for message in messages]
        response = await super().provider_request(model, messages, overhead, node, schema,
            0 if node == "investigate" else reserved_calls)
        if response is not None:
            raw = response.get("raw") if isinstance(response, dict) else response
            print(f"[DEBUG_LLM_RAW {node}] {getattr(raw, 'content', raw)}", file=sys.stderr)
        return response

    def _build_graph(self):
        graph = StateGraph(ReuseOpportunityState)
        graph.add_node("plan_investigation", phase_node("plan_investigation", self.plan_investigation))
        graph.add_node("investigate", phase_node("investigate", self.investigate))
        graph.add_node("tools", phase_node("tools", self.execute_investigation_tools))
        graph.add_edge(START, "plan_investigation")
        graph.add_conditional_edges("plan_investigation", self.route_after_plan,
            {"investigate": "investigate", "end": END})
        graph.add_conditional_edges("investigate", self.route_investigation,
            {"tools": "tools", "investigate": "investigate", "complete": END})
        graph.add_edge("tools", "investigate")
        return graph.compile()

    def model_context(self, node, state):
        if node == "plan_investigation":
            return self._planning_context
        if node == "investigate":
            return self._investigation_context(state)
        return super().model_context(node, state)

    def structured_correction_context(self, node, state):
        if node != "plan_investigation" and node != "investigate":
            return super().structured_correction_context(node, state)
        if node == "investigate":
            task = self._current(state)
            references = [
                record for record in self.references()
                if record.id in self._delivered_ids(state)
            ]
            inspected = sorted({record.path for record in references if record.kind == "source"})
            unverified = sorted(set(task.initial_targets) - set(inspected))
            correction = {
                "investigation_id": task.id,
                "document_claim_ids": list(task.document_claim_ids),
                "inspected_paths": inspected,
                "uninspected_initial_targets": unverified,
                "claims_to_assess": list(task.document_claim_ids),
                "target_policy": (
                    "Inspect indexed files relevant to the actual consumers or alternatives; outside "
                    "initial_targets require a concrete scope_expansion reason. Return only tools or an "
                    "honest inconclusive conclusion."
                ),
            }
            if getattr(self, "_last_validation_failure", None) is not None:
                correction["validation_failure"] = self._last_validation_failure
            return correction
        correction = {
            "phase": self._planning_context["phase"],
            "allowed_document_claim_ids": sorted(self._current_claim_ids),
            "allowed_capability_ids": sorted(getattr(self, "_capability_ids", set())),
            "target_policy": (
                "Use indexed_target_candidates exactly as shown, or use []. Documentary paths absent from "
                "repository_navigation.indexed_target_candidates are not verified initial targets."
            ),
        }
        if getattr(self, "_last_validation_failure", None) is not None:
            correction["validation_failure"] = self._last_validation_failure
        return correction

    def _fail(self, code):
        self._last_validation_failure = {
            "code": code,
            "reason": {
                "planning_unknown_target": "A proposed initial target is not a safe repository-relative indexed file or directory.",
                "planning_unknown_document_claim": "A cited claim is not in the current documentary evidence set.",
                "planning_unknown_capability": "A correlation references an unknown capability.",
                "planning_incomplete_correlation": "Not every supplied capability was grouped or explicitly excluded.",
                "planning_duplicate_investigation": "The response contains duplicate capability/claim investigations.",
                "planning_insufficient_evidence_conflict": "Investigations were returned despite insufficient evidence being declared.",
            }.get(code, "The supplied response did not satisfy its contract."),
        }
        raise PydanticCustomError(code, ReusePlanningResponse.validation_feedback[code])

    def prepare_structured_result(self, node, result, state):
        if isinstance(result, ReuseDiscoveryResponse):
            for item in result.capabilities:
                if set(item.document_claim_ids) - self._current_claim_ids:
                    self._fail("planning_unknown_document_claim")
        elif isinstance(result, ReuseCorrelationResponse):
            assigned = [key for group in result.groups for key in group.capability_ids]
            assigned += list(result.excluded_capabilities)
            if set(assigned) - self._capability_ids:
                self._fail("planning_unknown_capability")
            if len(assigned) != len(set(assigned)) or set(assigned) != self._capability_ids:
                self._fail("planning_incomplete_correlation")
            if any(not reason.strip() for reason in result.excluded_capabilities.values()):
                self._fail("planning_incomplete_correlation")
            for group in result.groups:
                if set(group.additional_document_claim_ids) - self._current_claim_ids:
                    self._fail("planning_unknown_document_claim")
        elif isinstance(result, ReusePlanningResponse):
            self._validate_plan(result, self._current_claim_ids)
        elif isinstance(result, ReuseInvestigationTurn):
            self._last_validation_failure = None
            try:
                result = self._normalize_investigation_result(result)
                # Structural repair stays in the existing bounded schema retry.
                # Missing evidence is evaluated by the controller after this
                # turn, so it can execute tools instead of rewording a close.
                self._validate_turn(result, state)
            except PydanticCustomError as error:
                failure = ReuseInvestigationTurn.validation_feedback.get(error.type)
                self._last_validation_failure = {
                    "code": error.type,
                    "reason": failure or "The investigation response did not satisfy its contract.",
                }
                raise
        return result

    @staticmethod
    def _normalize_investigation_result(result):
        conclusion = getattr(result, "conclusion", None)
        if conclusion is None:
            return result
        evidence = list(conclusion.evidence_ids)
        relationships = list(conclusion.relationship_ids)
        for candidate in conclusion.candidates:
            evidence += candidate.evidence_ids
            relationships += candidate.relationship_ids
        for assessment in conclusion.claim_assessments:
            evidence += assessment.code_evidence_ids
        for comparison in [*result.comparisons, *conclusion.comparisons]:
            evidence += comparison.shared_evidence_ids + comparison.other_evidence_ids
        return result.model_copy(update={"conclusion": conclusion.model_copy(update={
            "evidence_ids": list(dict.fromkeys(evidence)),
            "relationship_ids": list(dict.fromkeys(relationships)),
        })})

    def _validate_plan(self, response, allowed_claims):
        if response.insufficient_architectural_evidence and response.investigations:
            self._fail("planning_insufficient_evidence_conflict")
        paths = {item.path for item in self.tools.accessible_snapshot.files}
        normalized, seen = [], set()
        for item in response.investigations:
            claim_ids = sorted(set(item.document_claim_ids))
            if not claim_ids or set(claim_ids) - allowed_claims:
                self._fail("planning_unknown_document_claim")
            targets = []
            for target in item.initial_targets:
                try:
                    path = repository_relative_path(target)
                except RepositoryAccessError:
                    self._fail("planning_unknown_target")
                if path not in paths and not any(value.startswith(path + "/") for value in paths):
                    self._fail("planning_unknown_target")
                targets.append(path)
            identity = (item.capability.strip().casefold(), tuple(claim_ids))
            if identity in seen:
                self._fail("planning_duplicate_investigation")
            seen.add(identity)
            normalized.append(ReuseInvestigation(
                **item.model_dump(exclude={"document_claim_ids", "initial_targets"}),
                id=create_identifier("reuse-investigation", self.tools.accessible_snapshot.repository.snapshot_hash,
                    item.capability.strip().casefold(), claim_ids),
                document_claim_ids=claim_ids, initial_targets=sorted(set(targets)),
            ))
        return normalized

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
            "synthesis": {},
            "investigation_workspace": {},
        }

    def _context(self, phase, **data):
        architecture = self.request.documented_architecture
        return {
            "phase": phase,
            "objective": self.request.objective,
            "constraints": self.request.constraints,
            "targets": self.request.targets,
            "architecture_status": architecture.execution_status if architecture else None,
            "knowledge_issues": [item.model_dump(mode="json") for item in architecture.knowledge_issues]
                if architecture else [],
            "validation_errors": [item.model_dump(mode="json") for item in architecture.validation_errors]
                if architecture else [],
            **data,
        }

    def _request_characters(self, context, schema):
        """Conservative fallback envelope, including escaped messages and schema.

        Native schemas are no larger than this duplicated fallback envelope. The
        shared provider preflight remains authoritative for each actual attempt.
        """
        schema_text = json.dumps(schema.model_json_schema())
        prompt = self.config.prompts.get("plan_investigation")
        if prompt is None:
            prompt = (self.prompt_directory / "plan_investigation.md").read_text(encoding="utf-8")
        messages = [SystemMessage(content=prompt + "\nReturn only valid JSON matching this schema:\n" + schema_text),
            HumanMessage(content=json.dumps(context, ensure_ascii=False)),
            HumanMessage(content="Now execute plan_investigation. Return the requested JSON, no tools.")]
        return len(json.dumps([message.model_dump() for message in messages], default=str)) + len(schema_text)

    def _fits(self, context, schema):
        return self._request_characters(context, schema) <= min(
            self.config.max_context_characters, 2 * self.tools.context.input.budget.max_input_tokens_per_call)

    def _discovery_batches(self, records):
        # Keep documentary sections together where possible, without assigning
        # capabilities deterministically. Global correlation later sees all seeds.
        ordered = sorted(records.values(), key=lambda item: (tuple(item["section_ids"]), item["id"]))
        batches, current, oversized = [], [], []
        for record in ordered:
            projection = discovery_projection(record)
            candidate = [*current, projection]
            if not self._fits(self._context("identify", claims=candidate), ReuseDiscoveryResponse):
                if current:
                    batches.append(current)
                    current = []
                if not self._fits(self._context("identify", claims=[projection]), ReuseDiscoveryResponse):
                    oversized.append(record["id"])
                    continue
            current.append(projection)
        if current:
            batches.append(current)
        return batches, oversized

    async def _phase_call(self, state, context, schema, claim_ids):
        self._planning_context = context
        self._current_claim_ids = set(claim_ids)
        self._last_validation_failure = None
        characters = self._request_characters(context, schema)
        row = {"phase": context["phase"], "claim_ids": sorted(claim_ids),
            "estimated_request_characters": characters, "calls_before": self.calls,
            "attempted": False, "completed": False}
        self._phase_records.append(row)
        if not self._fits(context, schema):
            row["failure"] = "input_token_limit"
            return None
        result = await self.call("plan_investigation", state, schema)
        row.update(attempted=self.calls > row["calls_before"], completed=result is not None,
            model_attempts=self.calls - row["calls_before"])
        if result is not None:
            self._last_validation_failure = None
        elif getattr(self, "_last_validation_failure", None) is not None:
            row.update(failure=f"validation:{self._last_validation_failure['code']}",
                validation_failure=self._last_validation_failure)
        else:
            row["failure"] = self.stop or "model_or_schema_error"
        return result

    async def plan_investigation(self, state):
        records = documentary_records(self.request.documented_architecture)
        self._phase_records = []
        self._capability_ids = set()
        batches, oversized = self._discovery_batches(records)
        seeds, identified, limitations = {}, set(), []
        investigations, pending_groups, rejected_groups = [], [], []
        for batch in batches:
            response = await self._phase_call(state, self._context("identify", claims=batch),
                ReuseDiscoveryResponse, {item["id"] for item in batch})
            if response is None:
                break
            identified.update(item["id"] for item in batch)
            limitations.extend(response.limitations)
            for item in response.capabilities:
                key = f"capability-{len(seeds)}"
                seeds[key] = {"id": key, **item.model_dump(mode="json")}

        correlation = None
        # Even a single discovery batch is globally correlated; exact display
        # labels are not capability identity, and no host-side list union occurs.
        if seeds and not self.stop:
            self._capability_ids = set(seeds)
            catalog = [{key: record[key] for key in ("id", "subject", "category", "constraint")}
                for record in records.values()]
            correlation = await self._phase_call(state, self._context("correlate",
                capabilities=list(seeds.values()), claim_locator_catalog=catalog,
                discovery_complete=len(identified) == len(records)), ReuseCorrelationResponse, set(records))
            if correlation:
                limitations.extend(correlation.limitations)
        groups = correlation.groups if correlation else []
        unresolved_capabilities = sorted(seeds) if seeds and correlation is None else []
        paths = {item.path for item in self.tools.accessible_snapshot.files}
        for position, group in enumerate(groups):
            anchors = set(group.additional_document_claim_ids)
            anchors.update(key for seed_id in group.capability_ids for key in seeds[seed_id]["document_claim_ids"])
            # Recover original quotes/reasoning and complementary context from
            # the WHOLE input, not only the original discovery portion.
            selected = complementary_claims(anchors, records)
            originals = [records[key] for key in selected]
            context = self._context("formulate", capability_group=group.model_dump(mode="json"),
                capabilities=[seeds[key] for key in group.capability_ids], claims=originals,
                repository_navigation={
                    "indexed_target_candidates": relevant_paths(originals, paths),
                    "candidate_policy": (
                        "Candidates listed here are indexed files or directories containing indexed files. "
                        "Use only these exact repository-relative paths for initial_targets, or use []. "
                        "Paths from documentary text that are not listed here are not verified targets."
                    ),
                },
                documentary_context_complete=len(identified) == len(records),
                context_selection="All anchor, same-section and exact documented-entity claims; not guaranteed exhaustive.")
            # Navigation is optional; remove it before any evidence, never cut
            # quotations, reasoning, permissions or exceptions to force a fit.
            if not self._fits(context, ReusePlanningResponse):
                context["repository_navigation"]["indexed_target_candidates"] = []
            response = await self._phase_call(state, context, ReusePlanningResponse, set(selected))
            if response is None:
                pending_groups.append({"capability_ids": group.capability_ids,
                    "document_claim_ids": selected, "reason": self._phase_records[-1].get("failure")})
                if self.stop:
                    pending_groups.extend({"capability_ids": item.capability_ids,
                        "reason": self.stop} for item in groups[position + 1:])
                    break
                continue
            limitations.extend(response.limitations)
            if not response.investigations:
                rejected_groups.append({"capability_ids": group.capability_ids,
                    "reason": response.limitations or ["No actionable reuse investigation after reading original documentary context."]})
            investigations.extend(self._validate_plan(response, set(selected)))

        omitted = sorted(set(records) - identified)
        incomplete = bool(omitted or unresolved_capabilities or pending_groups)
        phase_failures = [row for row in self._phase_records if not row["completed"]]
        successful = any(row["completed"] for row in self._phase_records)
        status = "planning_partial" if incomplete or phase_failures else "planning_only"
        if records and not successful:
            status = "planning_blocked"
        if not records:
            limitations.append("No architectural claims supplied; no reuse intent inferred.")
        elif identified and not seeds:
            limitations.append("No documented reuse capabilities were identified in the processed claim projections; no source conclusion was made.")
        if incomplete or phase_failures:
            limitations.append("Planning is incomplete; unprocessed claims/capabilities/groups remain unresolved, not rejected.")
        architecture = self.request.documented_architecture
        if architecture and architecture.execution_status != "complete":
            limitations.append(f"Architecture Context coverage is {architecture.execution_status}; no global compliance conclusion.")
        if architecture and architecture.pending_categories:
            limitations.append("Pending documentary categories: " + ", ".join(architecture.pending_categories))
        if records:
            limitations.append("Discovery uses claim projections; final questions require original evidence and complementary context.")
        sent = {key for row in self._phase_records if row["attempted"] and row["phase"] != "correlate"
            for key in row["claim_ids"]}
        diagnostics = {
            "input_claim_count": len(records), "claims_sent_to_model": len(sent),
            "identified_claim_ids": sorted(identified), "omitted_claim_ids": omitted,
            "oversized_claim_ids": oversized, "batch_count": len(batches),
            "batches_processed": sum(row["completed"] for row in self._phase_records if row["phase"] == "identify"),
            "phases": self._phase_records,
            "unresolved_capability_ids": unresolved_capabilities,
            "excluded_capabilities": correlation.excluded_capabilities if correlation else {},
            "pending_groups": pending_groups, "rejected_groups": rejected_groups,
            "global_correlation_completed": correlation is not None,
            "formulation_reviewed_claim_ids": sorted({key for row in self._phase_records
                if row["phase"] == "formulate" and row["completed"] for key in row["claim_ids"]}),
            "capabilities": list(seeds.values()),
            "context_size_breakdown": {"original_claim_characters": len(json.dumps(list(records.values()), ensure_ascii=False))},
        }
        cited = {key for item in investigations for key in item.document_claim_ids}
        # The full reviewed documentary context is retained, including exceptions
        # not explicitly cited by the final questions.
        reviewed = {key for row in self._phase_records if row["phase"] == "formulate" and row["completed"]
            for key in row["claim_ids"]}
        hypotheses = [Hypothesis(id=item.id, question=item.question, priority=item.priority,
            evidence_needed=item.objectives + item.reuse_criteria + item.independent_implementation_criteria)
            for item in investigations]
        plan = ReuseOpportunityPlan(objectives=[self.request.objective],
            components=list(dict.fromkeys(path for item in investigations for path in item.initial_targets)),
            hypotheses=hypotheses, investigations=investigations,
            document_claims={key: records[key] for key in records if key in cited | reviewed},
            limitations=list(dict.fromkeys(limitations)), planning_diagnostics=diagnostics)
        reason = self.stop or (phase_failures[0].get("failure") if phase_failures else None) or (
            "input_token_limit" if status == "planning_blocked" and oversized else
            "planning_completed" if status == "planning_only" else "planning_partial")
        result = self.result_schema(repository_id=state["repository_id"], commit=state["commit"],
            snapshot_hash=self.tools.context.input.snapshot_hash, objective=self.request.objective,
            plan=plan, findings=[], hypotheses=hypotheses,
            missing_information=[] if status == "planning_only" else ["Unresolved planning work is retained in planning_diagnostics."],
            limitations=plan.limitations + ["Planning only; no source inspection, finding or compliance conclusion."],
            termination_reason=reason, model_calls=self.calls, tool_calls=self.tools.budget_usage.tool_calls,
            iterations=0, accounted_tokens=self.tokens, estimated_tokens=self.estimates,
            evidence=[], deferred_stages=self.deferred_stages, status=status, planning_diagnostics=diagnostics)
        return {"plan": plan, "result": result, "hypotheses": hypotheses,
            "candidates": [], "investigation_results": [],
            "current_investigation": 0, "pending_queries": [],
            "active_query_keys": [], "query_cache": {},
            "initial_evidence_loaded": False, "coverage_recovery_done": False,
            "task_limitations": [],
            "model_calls": self.calls, "tool_calls": result.tool_calls,
            "limitations": result.limitations, "termination_reason": reason}
