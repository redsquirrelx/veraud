"""Context-qualified, read-only adaptability investigation on the shared runtime."""

import hashlib
import json
from collections import Counter
from pathlib import Path
from time import monotonic
from uuid import uuid4

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from .....runtimes.investigation.agent import InvestigationAgent, InvestigationExecution
from .....runtimes.investigation.provider import lean_schema
from .....runtimes.investigation.state import InvestigationState
from .....runtimes.repository.tools import TOOL_SCHEMAS
from .config import ComponentAdaptabilityConfig
from .discovery import discover
from .schemas import (
    AdaptabilityEvaluation,
    AdaptabilityFinding,
    ComponentAdaptabilityRequest,
    ComponentAdaptabilityResult,
    ExaminedConstraint,
    InspectionDecision,
    InspectRoute,
    ValidationRoute,
)


class ComponentAdaptabilityExecution(InvestigationExecution):
    trace_name = "component-adaptability"
    tool_prefix = "component-adaptability"
    prompt_directory = Path(__file__).parent / "prompts"
    evaluation_schema = AdaptabilityEvaluation
    finding_schema = AdaptabilityFinding
    result_schema = ComponentAdaptabilityResult

    def __init__(self, model, config, tools, request):
        self.trace, self.durations = [], {}
        self.final_reason, self.limited = "", False
        self.context_node = ""
        self.duplicate_assessments = set()
        tools.limits = tools.limits.model_copy(update={"compact": True,
            "max_source_lines": min(tools.limits.max_source_lines, config.max_source_lines),
            "max_source_characters": min(tools.limits.max_source_characters, config.max_source_characters)})
        super().__init__(model, config, tools, request)
        self.coverage = discover(tools.accessible_snapshot, request, config)
        self.components = {c.component_id: c for c in self.coverage.selected_components}
        snapshot = tools.accessible_snapshot
        self.files = {f.id: f for f in snapshot.files}
        self.symbols = {s.id: s for s in snapshot.symbols}
        self.relationships = {r.id: r for r in snapshot.relationships}
        self.anchors = {e.id: e for e in snapshot.evidence}

    def structured_schema(self, schema):
        return lean_schema(schema) if isinstance(self.model, BaseChatModel) else schema

    async def call(self, node, state, schema=None):
        self.context_node = node
        return await super().call(node, state, schema)

    def _context(self, state):
        return super()._context(state) | {
            "quality_attribute": "reusability", "target_context": self.request.target_context,
            "component_scope": self.request.targets,
            "selected_components": [c.model_dump() for c in self.coverage.selected_components],
            "discovery_coverage": self.coverage.model_dump(exclude={"selected_components"}),
            "available_tools": self.config.tools,
            "allowed_tool_argument_schemas": {name: TOOL_SCHEMAS[name].model_json_schema() for name in self.config.tools}
                if self.context_node == "investigate" else {},
            "visited_symbols": sorted({s for r in self.references() for s in r.symbol_ids}),
            "discovery_is_navigation_not_evidence": True,
        }

    async def investigate(self, state):
        # Explicit structured decisions replace the legacy free-text "ready" response.
        if self.calls >= self.call_limit - 2 or self.tools.budget_usage.tool_calls >= self.tool_limit:
            return {"messages": [AIMessage(content="", tool_calls=[])], "model_calls": self.calls}
        decision = await self.call("investigate", state, InspectionDecision)
        calls = []
        if decision is not None:
            try:
                for item in decision.tool_requests:
                    if item.name not in self.config.tools:
                        raise ValueError("Tool is not allowed for this invocation")
                    arguments = TOOL_SCHEMAS[item.name].model_validate_json(item.arguments_json).model_dump()
                    calls.append({"name": item.name, "args": arguments, "id": "inspect-" + uuid4().hex})
            except ValueError:
                self.stop = "invalid_inspection_decision"
                self.issues.append("Inspection tool arguments or permissions failed host validation; no requests executed.")
                calls = []
        remaining = self.tool_limit - self.tools.budget_usage.tool_calls
        if len(calls) > remaining:
            self.issues.append("Inspection batch exceeded remaining tool allowance; only the bounded prefix was executed.")
        return {"messages": [AIMessage(content="", tool_calls=calls[:remaining])], "model_calls": self.calls}

    def record(self, event):
        self.trace.append(event)
        self.logger.info("component_adaptability: %s", event)

    def route_investigation(self, state) -> InspectRoute:
        route = InspectRoute.USE_TOOLS if super().route_investigation(state) == "tools" else InspectRoute.VALIDATE
        self.record("route:" + route.value)
        return route

    def is_sufficient(self, state) -> ValidationRoute:
        evaluation = state["evaluation"]
        reason = self.stop
        if not reason and self.remaining_seconds() <= 0:
            reason = "time_limit"
        if not reason and evaluation and evaluation.sufficient and not evaluation.missing_information:
            reason = "sufficient_evidence"
        if not reason and evaluation and not evaluation.can_investigate_further:
            reason = "unverifiable"
        if not reason:
            reason = ("iteration_limit" if state["iterations"] >= self.config.max_iterations else
                      "tool_call_limit" if self.tools.budget_usage.tool_calls >= self.tool_limit else
                      "model_call_limit" if self.calls >= self.call_limit - 2 else
                      "no_actionable_gap" if evaluation and not evaluation.missing_information else "")
        self.final_reason = reason
        self.limited = bool(reason and reason != "sufficient_evidence")
        route = ValidationRoute.LIMITED_FINALIZE if self.limited else ValidationRoute.FINALIZE if reason else ValidationRoute.INSPECT
        self.record("route:" + route.value)
        return route

    async def review_findings(self, state):
        update = await super().review_findings(state)
        update["termination_reason"] = self.stop or self.final_reason or update["termination_reason"]
        return update

    @staticmethod
    def covered(records, file_id, start, end):
        cursor = start
        for r in sorted((r for r in records if r.kind == "source" and r.file_id == file_id), key=lambda r: r.start_line):
            if r.start_line > cursor:
                break
            cursor = max(cursor, r.end_line + 1)
        return cursor > end

    def normalize(self, assessment, hypotheses):
        component = self.components.get(assessment.component_id)
        ids = [*assessment.supporting_evidence_ids, *assessment.counterevidence_ids, *assessment.seam_evidence_ids,
               *[i for u in assessment.usage for i in u.evidence_ids]]
        references = {r.id: r for r in self.references()}
        evidence, mismatch = self.verify_references([references[i] for i in dict.fromkeys(ids) if i in references])
        issues = []
        if set(ids) - references.keys():
            issues.append("unknown_evidence_ids")
        if mismatch:
            issues.append("commit_mismatch")
        if not component:
            issues.append("component_not_selected_or_out_of_scope")
        if assessment.id in self.duplicate_assessments:
            issues.append("duplicate_assessment_id")
        if assessment.hypothesis_id not in hypotheses:
            issues.append("unknown_hypothesis")
        own = [r for r in evidence if r.id in assessment.supporting_evidence_ids]
        if not component or not self.covered(own, component.file_id, component.start_line, component.end_line):
            issues.append("component_body_not_inspected")
        if self.request.target_context is not None:
            if assessment.context_basis != "explicit" or assessment.assessed_context != self.request.target_context:
                issues.append("explicit_target_context_mismatch")
        elif assessment.context_basis != "plausible" or not assessment.assumptions:
            issues.append("unspecified_target_requires_qualified_plausible_context")
        if not all(t.strip() for t in [assessment.constraint_key, assessment.assessed_context, assessment.adaptation_impact,
                assessment.adaptation_effort, assessment.seam_analysis, assessment.counterevidence_analysis, *assessment.observed_facts,
                *assessment.assumptions]):
            issues.append("concrete_facts_tradeoffs_and_seam_analysis_required")
        seam = [r for r in evidence if r.id in assessment.seam_evidence_ids and r.kind == "source"
                and component and r.file_id == component.file_id
                and r.start_line <= component.end_line and r.end_line >= component.start_line]
        if assessment.conclusion != "unknown" and not seam:
            issues.append("source_backed_seam_check_required")
        for usage in assessment.usage:
            symbol = self.symbols.get(usage.caller_id)
            source = self.files.get(symbol.file_id if symbol else usage.caller_id)
            edge = self.relationships.get(usage.relationship_id)
            records = [r for r in evidence if r.id in usage.evidence_ids]
            valid_edge = (component and source and edge and edge.resolution == "internal" and edge.kind != "contains"
                and edge.source_id in {usage.caller_id, source.id}
                and edge.target_id in {component.component_id, component.file_id}
                and usage.caller_id not in {component.component_id, component.file_id})
            anchors = [self.anchors[i] for i in edge.evidence_ids if i in self.anchors] if edge else []
            anchor_read = any(a.start_line is not None and self.covered(records, a.file_id, a.start_line, a.end_line or a.start_line) for a in anchors)
            body_read = source and self.covered(records, source.id, symbol.start_line if symbol else 1,
                                               symbol.end_line if symbol else source.line_count or 1)
            if not valid_edge or not anchor_read or not body_read or not usage.instantiation_configuration.strip():
                issues.append("usage_or_configuration_not_verified")
        if assessment.conclusion == "verified_obstacle":
            if self.request.target_context is None:
                issues.append("verified_obstacle_requires_explicit_target")
            if not assessment.usage:
                issues.append("verified_obstacle_requires_usage_inspection")
            if assessment.unknowns:
                issues.append("verified_obstacle_has_unresolved_unknowns")
        return ExaminedConstraint(**assessment.model_dump(), component=component, evidence=evidence,
            validation_issues=list(dict.fromkeys(issues)), validation_status="insufficient_evidence" if issues else "source_backed")

    def candidate_issues(self, candidate, assessments):
        linked = [assessments[i] for i in candidate.assessment_ids if i in assessments]
        if not linked or len(linked) != len(set(candidate.assessment_ids)):
            return True
        keys = {(a.constraint_type, a.constraint_key.strip().casefold(), a.assessed_context) for a in linked}
        return (len(keys) != 1 or candidate.kind != "design_observation"
            or any(a.validation_issues or a.conclusion != candidate.classification or a.constraint_type != candidate.constraint_type for a in linked)
            or set(candidate.components) != {a.component_id for a in linked}
            or not {r.id for a in linked for r in a.evidence} <= set(candidate.evidence_ids)
            or not set(candidate.evidence_ids) <= {r.id for r in self.references()})

    def unassessed(self, evaluation, assessments):
        complete = {a.component_id for a in assessments if not a.validation_issues and a.conclusion != "unknown"}
        if evaluation:
            # An empty result must still inspect the component, not merely its name.
            for identifier in evaluation.cleared_components:
                c = self.components.get(identifier)
                if c and self.covered(self.references(), c.file_id, c.start_line, c.end_line):
                    complete.add(identifier)
        return sorted(self.components.keys() - complete)

    async def evaluate_evidence(self, state):
        update = await super().evaluate_evidence(state)
        current = update["evaluation"]
        if current is None:
            return update
        counts = Counter(a.id for a in current.constraint_assessments)
        self.duplicate_assessments.difference_update(counts)
        self.duplicate_assessments.update(i for i, count in counts.items() if count > 1)
        prior = state["evaluation"]
        if prior:
            current = current.model_copy(update={
                "constraint_assessments": [*current.constraint_assessments, *[a for a in prior.constraint_assessments if a.id not in counts]],
                "candidates": [*current.candidates, *[c for c in prior.candidates if c.id not in {c.id for c in current.candidates}]],
            })
        assessments = [self.normalize(a, {h.id for h in update["hypotheses"]}) for a in current.constraint_assessments]
        by_id = {a.id: a for a in assessments}
        gaps = list(current.missing_information)
        if len(assessments) > self.config.max_constraints:
            self.stop = "constraint_limit"
            gaps.append("Constraint assessment count exceeds max_constraints.")
        for a in assessments:
            if a.validation_issues or a.conclusion == "unknown":
                gaps.append("Resolve constraint " + a.id + ": " + ", ".join(a.validation_issues or a.unknowns or ["unverified obstacle"]))
        for c in current.candidates:
            if self.candidate_issues(c, by_id):
                gaps.append("Resolve candidate " + c.id + ": context, seam, usage or citation support is incomplete.")
        for identifier in self.unassessed(current, assessments):
            gaps.append("Inspect component " + identifier + " or state the specific evidence blocker.")
        if set(current.cleared_components) - self.components.keys() or not current.coverage_rationale.strip():
            gaps.append("Coverage declarations must identify selected components and a concrete rationale.")
        gaps.extend("Resolve hypothesis " + h.id + " or state a specific blocker." for h in update["hypotheses"] if h.status in {"pending", "inconclusive"})
        update["evaluation"] = current.model_copy(update={"sufficient": current.sufficient and not gaps, "missing_information": list(dict.fromkeys(gaps))})
        update["missing_information"] = update["evaluation"].missing_information
        return update

    def tool_failures(self, state):
        failures = [f"{m.tool}:{m.call_id}:{m.status}" for m in self.tools.tool_measurements if m.status != "ok"]
        for m in state["messages"]:
            if isinstance(m, ToolMessage):
                failed = m.status == "error"
                try:
                    payload = json.loads(m.content)
                    failed |= isinstance(payload, dict) and payload.get("status") == "error"
                except (ValueError, TypeError):
                    pass
                if failed:
                    failures.append(f"tool_node:{m.name or 'unknown'}:{m.tool_call_id}:error")
        return list(dict.fromkeys(failures))

    def finalize(self, state):
        result = super().finalize(state)["result"]
        evaluation = state["evaluation"]
        assessments = [self.normalize(a, {h.id for h in result.hypotheses}) for a in evaluation.constraint_assessments] if evaluation else []
        by_id = {a.id: a for a in assessments}
        findings, seen = [], {}
        for finding in result.findings:
            linked = [by_id[i] for i in finding.assessment_ids if i in by_id]
            if self.candidate_issues(finding, by_id) and finding.validation_status != "rejected":
                finding = finding.model_copy(update={"validation_status": "insufficient_evidence", "confidence": 0,
                    "review_rationale": "Host validation failed: require inspected component, source-backed seam analysis, qualified target context, verified usage for demonstrated obstacles and complete citations."})
            key = (finding.constraint_type, linked[0].constraint_key.strip().casefold() if linked else finding.id,
                   linked[0].assessed_context if linked else "")
            stable_id = "ADAPT-" + hashlib.sha256(json.dumps(key).encode()).hexdigest()[:16]
            finding = finding.model_copy(update={"stable_id": stable_id,
                "assessed_context": linked[0].assessed_context if linked else "",
                "adaptation_impact": "\n".join(dict.fromkeys(a.adaptation_impact for a in linked)),
                "adaptation_effort": "\n".join(dict.fromkeys(a.adaptation_effort for a in linked)),
                "assumptions": list(dict.fromkeys(s for a in linked for s in a.assumptions)),
                "mitigation_options": list(dict.fromkeys(s for a in linked for s in a.mitigation_options))})
            if finding.validation_status == "accepted":
                if key in seen:
                    index = seen[key]
                    first = findings[index]
                    findings[index] = first.model_copy(update={
                        "evidence": list({r.id: r for r in [*first.evidence, *finding.evidence]}.values()),
                        "evidence_ids": list(dict.fromkeys([*first.evidence_ids, *finding.evidence_ids])),
                        "components": list(dict.fromkeys([*first.components, *finding.components])),
                        "assessment_ids": list(dict.fromkeys([*first.assessment_ids, *finding.assessment_ids])),
                        "assumptions": list(dict.fromkeys([*first.assumptions, *finding.assumptions])),
                        "mitigation_options": list(dict.fromkeys([*first.mitigation_options, *finding.mitigation_options])),
                        "adaptation_impact": "\n".join(dict.fromkeys([first.adaptation_impact, finding.adaptation_impact])),
                        "adaptation_effort": "\n".join(dict.fromkeys([first.adaptation_effort, finding.adaptation_effort])),
                        "classification": "context_dependent_risk" if "context_dependent_risk" in {first.classification, finding.classification} else "verified_obstacle",
                        "confidence": min(first.confidence, finding.confidence),
                    })
                    finding = finding.model_copy(update={"duplicate_of": first.id, "validation_status": "rejected", "confidence": 0,
                        "review_rationale": "Duplicate cause consolidated into " + first.id + "; original candidate retained."})
                else:
                    seen[key] = len(findings)
            findings.append(finding)
        pending = self.unassessed(evaluation, assessments)
        failures = self.tool_failures(state)
        complete = (not self.limited and result.termination_reason == "sufficient_evidence" and result.plan is not None
            and state["review"] is not None and not pending and not failures and not result.missing_information
            and not any(a.validation_issues or a.conclusion == "unknown" for a in assessments)
            and not any(f.validation_status == "insufficient_evidence" for f in findings)
            and not any(h.status in {"pending", "inconclusive"} for h in result.hypotheses))
        status = "completed" if complete else "failed" if result.plan is None and not self.references() else "partial"
        coverage = self.coverage.model_copy(update={"unassessed_components": pending,
            "inspected_paths": sorted({r.path for r in self.references() if r.kind == "source"})})
        limitations = [s.replace("boundary compliance", "component adaptability") for s in result.limitations]
        limitations.extend([
            "Static discovery hints and valid citations do not prove runtime behavior, mandatory dependency use or absence of extension points.",
            "Adaptation effort is qualitative; findings are context-qualified observations, not automatic refactors or measured cost estimates.",
            "Coverage is selective; bounded tool transcripts can reach the shared context limit. No automatic history compaction is implemented."])
        if evaluation and not evaluation.can_investigate_further:
            limitations.append("Investigation blocker: " + evaluation.continuation_reason)
        if self.request.target_context is None:
            limitations.append("Target context was not specified; plausible contexts are assumptions, not user requirements.")
        return {"result": ComponentAdaptabilityResult.model_validate({**result.model_dump(), "status": status,
            "findings": findings, "examined_constraints": assessments, "target_context": self.request.target_context,
            "coverage": coverage, "tool_failures": failures, "execution_trace": self.trace,
            "summary": f"{len(self.components) - len(pending)}/{len(self.components)} selected components investigated; "
                       f"{sum(f.validation_status == 'accepted' for f in findings)} supported context-qualified observations; status={status}.",
            "limitations": limitations, "node_durations_seconds": self.durations,
            "tool_activity": [{"call_id": m.call_id, "tool": m.tool, "status": m.status,
                               "seconds": m.seconds, "cache_hit": m.cache_hit} for m in self.tools.tool_measurements]})}

    def _build_graph(self):
        graph = StateGraph(InvestigationState)

        def observed(name, fn):
            async def node(state):
                self.record(name)
                started = monotonic()
                try:
                    answer = fn(state)
                    if hasattr(answer, "__await__"):
                        answer = await answer
                finally:
                    seconds = monotonic() - started
                    self.durations[name] = self.durations.get(name, 0) + seconds
                    self.logger.info("component_adaptability: node=%s seconds=%g model_calls=%s tool_calls=%s tokens=%s stop=%s",
                        name, seconds, self.calls, self.tools.budget_usage.tool_calls, self.tokens, self.stop)
                if "result" in answer:
                    answer["result"] = answer["result"].model_copy(update={"node_durations_seconds": dict(self.durations)})
                return answer
            return node

        for name in ("plan_investigation", "investigate", "evaluate_evidence", "review_findings", "finalize"):
            graph.add_node(name, observed(name, getattr(self, name)))
        graph.add_node("limited_review", observed("limited_review", self.review_findings))
        graph.add_node("limited_finalize", observed("limited_finalize", self.finalize))
        graph.add_node("tools", observed("tools", ToolNode(self.native_tools, handle_tool_errors=True).ainvoke))
        graph.add_edge(START, "plan_investigation")
        graph.add_edge("plan_investigation", "investigate")
        graph.add_conditional_edges("investigate", self.route_investigation,
            {InspectRoute.USE_TOOLS: "tools", InspectRoute.VALIDATE: "evaluate_evidence"})
        graph.add_edge("tools", "investigate")
        graph.add_conditional_edges("evaluate_evidence", self.is_sufficient,
            {ValidationRoute.INSPECT: "investigate", ValidationRoute.FINALIZE: "review_findings", ValidationRoute.LIMITED_FINALIZE: "limited_review"})
        graph.add_edge("review_findings", "finalize")
        graph.add_edge("limited_review", "limited_finalize")
        graph.add_edge("finalize", END)
        graph.add_edge("limited_finalize", END)
        return graph.compile()


class ComponentAdaptabilityAgent(InvestigationAgent):
    request_type = ComponentAdaptabilityRequest
    config_type = ComponentAdaptabilityConfig
    execution_type = ComponentAdaptabilityExecution
    trace_name = "component-adaptability"
    agent_type = "component-adaptability"
