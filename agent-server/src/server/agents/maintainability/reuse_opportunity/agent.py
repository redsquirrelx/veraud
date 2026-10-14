"""Evidence-grounded reuse research, sharing the existing investigator runtime."""

import json
from collections import Counter
from pathlib import Path

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from ...modularity_runtime.agent import InvestigationAgent, InvestigationExecution
from ...modularity_runtime.provider import lean_schema
from ...modularity_runtime.state import InvestigationState
from .discovery import discover
from .schemas import (
    ExaminedGroup,
    InspectRoute,
    ReuseEvaluation,
    ReuseFinding,
    ReuseOpportunityConfig,
    ReuseOpportunityRequest,
    ReuseOpportunityResult,
    ValidationRoute,
)


class ReuseOpportunityExecution(InvestigationExecution):
    trace_name = "reuse-opportunity"
    tool_prefix = "reuse-opportunity"
    prompt_directory = Path(__file__).parent / "prompts"
    evaluation_schema = ReuseEvaluation
    finding_schema = ReuseFinding
    result_schema = ReuseOpportunityResult

    def __init__(self, model, config, tools, request):
        self.trace = []
        self.final_reason = ""
        self.limited = False
        self.duplicate_groups = set()
        # The toolset is fresh and invocation-local. Tighten, never loosen, its
        # caller-supplied read bounds; reuse its existing cache/compact serializer.
        tools.limits = tools.limits.model_copy(update={"compact": True,
            "max_source_lines": min(tools.limits.max_source_lines, config.max_source_lines),
            "max_source_characters": min(tools.limits.max_source_characters, config.max_source_characters)})
        super().__init__(model, config, tools, request)
        self.coverage = discover(tools.accessible_snapshot, request, config)
        self.groups = {g.id: g for g in self.coverage.selected_groups}
        snapshot = tools.accessible_snapshot
        self.files = {f.id: f for f in snapshot.files}
        self.symbols = {s.id: s for s in snapshot.symbols}
        self.relationships = {r.id: r for r in snapshot.relationships}
        self.anchors = {e.id: e for e in snapshot.evidence}

    def structured_schema(self, schema):
        return lean_schema(schema) if isinstance(self.model, BaseChatModel) else schema

    def _context(self, state):
        return super()._context(state) | {
            "quality_attribute": "reusability", "declaration_scope": self.request.targets,
            "candidate_groups": [g.model_dump() for g in self.coverage.selected_groups],
            "discovery_coverage": self.coverage.model_dump(exclude={"selected_groups"}),
            "candidate_queue": [g for g in self.groups if not state["evaluation"] or
                g not in {a.group_id for a in state["evaluation"].group_assessments}],
            "discovery_is_navigation_not_proof": True,
        }

    def record(self, event):
        self.trace.append(event)
        self.logger.info("reuse_opportunity: %s", event)

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
        if not reason:
            reason = ("iteration_limit" if state["iterations"] >= self.config.max_iterations else
                      "tool_call_limit" if self.tools.budget_usage.tool_calls >= self.tool_limit else
                      "model_call_limit" if self.calls >= self.call_limit - 2 else
                      "no_actionable_gap" if evaluation and not evaluation.missing_information else "")
        self.final_reason = reason
        self.limited = bool(reason and reason != "sufficient_evidence")
        route = (ValidationRoute.LIMITED_FINALIZE if self.limited else
                 ValidationRoute.FINALIZE if reason else ValidationRoute.INSPECT)
        self.record("route:" + route.value)
        return route

    async def review_findings(self, state):
        update = await super().review_findings(state)
        update["termination_reason"] = self.stop or self.final_reason or update["termination_reason"]
        return update

    def covered(self, records, file_id, start, end):
        """Allow adjacent bounded reads, but never a declaration-only excerpt for a body."""
        cursor = start
        for r in sorted((r for r in records if r.kind == "source" and r.file_id == file_id),
                        key=lambda r: r.start_line):
            if r.start_line > cursor:
                break
            cursor = max(cursor, r.end_line + 1)
        return cursor > end

    def normalize(self, assessment, hypotheses):
        group = self.groups.get(assessment.group_id)
        ids = [i for p in assessment.implementations for i in p.evidence_ids]
        ids.extend(i for c in assessment.callers for i in c.evidence_ids)
        references = {r.id: r for r in self.references()}
        records, mismatch = self.verify_references([references[i] for i in dict.fromkeys(ids) if i in references])
        issues = []
        if set(ids) - references.keys():
            issues.append("unknown_evidence_ids")
        if mismatch:
            issues.append("commit_mismatch")
        if not group:
            issues.append("unknown_or_out_of_scope_group")
        if assessment.group_id in self.duplicate_groups:
            issues.append("duplicate_group_assessment")
        if assessment.hypothesis_id not in hypotheses:
            issues.append("unknown_hypothesis")
        members = {m.component_id: m for m in group.members} if group else {}
        if Counter(p.component_id for p in assessment.implementations) != Counter(members.keys()):
            issues.append("group_requires_distinct_selected_implementations")
        for profile in assessment.implementations:
            member = members.get(profile.component_id)
            own = [r for r in records if r.id in profile.evidence_ids]
            if not member or not self.covered(own, member.file_id, member.start_line, member.end_line):
                issues.append("implementation_body_not_inspected:" + profile.component_id)
            if not all(value.strip() for key, value in profile.model_dump().items()
                       if key not in {"evidence_ids", "component_id"}):
                issues.append("empty_behavior_comparison")
        inspected_callers = set()
        for caller in assessment.callers:
            member = members.get(caller.implementation_id)
            symbol = self.symbols.get(caller.caller_id)
            source = self.files.get(symbol.file_id if symbol else caller.caller_id)
            edge = self.relationships.get(caller.relationship_id)
            own = [r for r in records if r.id in caller.evidence_ids]
            valid_edge = (member and source and edge and edge.resolution == "internal" and edge.kind != "contains"
                and edge.source_id in {caller.caller_id, source.id}
                and edge.target_id in {member.component_id, member.file_id}
                and caller.caller_id not in {member.component_id, member.file_id})
            anchors = [self.anchors[i] for i in edge.evidence_ids if i in self.anchors] if edge else []
            anchor_read = any(a.start_line is not None and self.covered(own, a.file_id, a.start_line, a.end_line or a.start_line)
                              for a in anchors)
            body_read = source and (self.covered(own, source.id, symbol.start_line, symbol.end_line) if symbol else
                                   self.covered(own, source.id, 1, source.line_count or 1))
            if not valid_edge or not anchor_read or not body_read or not caller.constraints.strip():
                issues.append("caller_constraints_not_verified:" + caller.implementation_id)
            else:
                inspected_callers.add(caller.implementation_id)
        if assessment.classification == "recommended":
            if set(members) - inspected_callers:
                issues.append("recommended_requires_inspected_callers_for_each_implementation")
            if assessment.unknowns:
                issues.append("recommended_has_unresolved_unknowns")
        required_text = (assessment.shared_responsibility, assessment.meaningful_differences,
            assessment.variation_points, assessment.proposed_boundary, assessment.expected_benefit,
            assessment.risks_tradeoffs, assessment.migration_complexity, assessment.counterevidence_analysis,
            assessment.rationale)
        if not all(t.strip() for t in required_text):
            issues.append("concrete_tradeoff_analysis_required")
        return ExaminedGroup(**assessment.model_dump(), members=list(members.values()), evidence=records,
            validation_issues=list(dict.fromkeys(issues)),
            validation_status="insufficient_evidence" if issues else "source_backed")

    def finding_issues(self, candidate, assessments):
        assessment = assessments.get(candidate.group_id)
        if not assessment or assessment.validation_issues:
            return True
        members = {m.component_id for m in assessment.members}
        return (candidate.classification != assessment.classification or candidate.kind != "design_observation"
                or set(candidate.components) != members
                or not {r.id for r in assessment.evidence} <= set(candidate.evidence_ids)
                or not set(candidate.evidence_ids) <= {r.id for r in self.references()})

    def tool_failures(self, state):
        failures = [f"{m.tool}:{m.call_id}:{m.status}" for m in self.tools.tool_measurements if m.status != "ok"]
        # ToolNode argument/schema failures happen before RepositoryToolset's ledger.
        for message in state["messages"]:
            if not isinstance(message, ToolMessage):
                continue
            failed = message.status == "error"
            if isinstance(message.content, str):
                try:
                    payload = json.loads(message.content)
                    failed |= isinstance(payload, dict) and payload.get("status") == "error"
                except ValueError:
                    pass
            if failed:
                failures.append(f"tool_node:{message.name or 'unknown'}:{message.tool_call_id}:error")
        return list(dict.fromkeys(failures))

    async def evaluate_evidence(self, state):
        update = await super().evaluate_evidence(state)
        current = update["evaluation"]
        if current is None:
            return update
        counts = Counter(a.group_id for a in current.group_assessments)
        self.duplicate_groups.difference_update(counts)
        self.duplicate_groups.update(i for i, count in counts.items() if count > 1)
        prior = state["evaluation"]
        if prior is not None:
            current = current.model_copy(update={
                "group_assessments": [*current.group_assessments, *[a for a in prior.group_assessments if a.group_id not in counts]],
                "candidates": [*current.candidates, *[c for c in prior.candidates if c.id not in {c.id for c in current.candidates}]],
            })
        assessed = [self.normalize(a, {h.id for h in update["hypotheses"]}) for a in current.group_assessments]
        by_id = {a.group_id: a for a in assessed}
        gaps = list(current.missing_information)
        if len(current.group_assessments) > self.config.max_groups:
            gaps.append("Group assessment count exceeds the configured max_groups budget.")
        for a in assessed:
            if a.validation_issues:
                gaps.append("Resolve group " + a.group_id + ": " + ", ".join(a.validation_issues))
        for identifier in self.groups.keys() - by_id.keys():
            gaps.append("Inspect selected group " + identifier + " or report why comparison is blocked.")
        for c in current.candidates:
            if self.finding_issues(c, by_id):
                gaps.append("Resolve candidate " + c.id + ": behavior comparison, classification, components or citations are unsupported.")
        for h in update["hypotheses"]:
            if h.status in {"pending", "inconclusive"}:
                gaps.append("Resolve hypothesis " + h.id + " or identify a specific evidence blocker.")
        update["evaluation"] = current.model_copy(update={"sufficient": current.sufficient and not gaps,
            "missing_information": list(dict.fromkeys(gaps))})
        update["missing_information"] = update["evaluation"].missing_information
        return update

    def finalize(self, state):
        result = super().finalize(state)["result"]
        evaluation = state["evaluation"]
        assessments = [self.normalize(a, {h.id for h in result.hypotheses}) for a in evaluation.group_assessments] if evaluation else []
        by_id = {a.group_id: a for a in assessments}
        findings = []
        seen = {}
        for finding in result.findings:
            if self.finding_issues(finding, by_id) and finding.validation_status != "rejected":
                finding = finding.model_copy(update={"validation_status": "insufficient_evidence", "confidence": 0,
                    "review_rationale": "Host validation requires both source implementations, behavior/tradeoff analysis, matching classification and citations; recommended reuse also requires inspected callers and no unresolved unknowns."})
            finding = finding.model_copy(update={"stable_id": "REUSE-" + finding.group_id.removeprefix("ROG-")})
            if finding.classification == "not_recommended":
                finding = finding.model_copy(update={"severity": "info"})
            if finding.validation_status == "accepted":
                if finding.group_id in seen:
                    finding = finding.model_copy(update={"duplicate_of": seen[finding.group_id], "validation_status": "rejected",
                        "confidence": 0, "review_rationale": "Duplicate group conclusion retained for traceability; see " + seen[finding.group_id]})
                else:
                    seen[finding.group_id] = finding.id
            findings.append(finding)
        pending = sorted(self.groups.keys() - {a.group_id for a in assessments if not a.validation_issues})
        tool_failures = self.tool_failures(state)
        complete = (not self.limited and result.termination_reason == "sufficient_evidence" and result.plan is not None
            and state["review"] is not None and not pending and not result.missing_information and not tool_failures
            and not any(f.validation_status == "insufficient_evidence" for f in findings)
            and not any(h.status in {"pending", "inconclusive"} for h in result.hypotheses))
        status = "completed" if complete else "failed" if result.plan is None and not self.references() else "partial"
        coverage = self.coverage.model_copy(update={"unassessed_groups": pending,
            "inspected_paths": sorted({r.path for r in self.references() if r.kind == "source"})})
        limitations = [*result.limitations,
            "Discovery is bounded static navigation, not a semantic equivalence or measured savings claim; no findings does not certify absence of opportunities.",
            "Caller links are static internal relationships, not proof of runtime dispatch. Missing/dynamic consumers constrain recommendations.",
            "Qualitative behavior, benefits and migration risks remain model judgments; accepted findings are proposals, never mandatory refactors."]
        limitations = [s.replace("boundary compliance", "absence of reuse opportunities") for s in limitations]
        return {"result": ReuseOpportunityResult.model_validate({**result.model_dump(), "findings": findings,
            "examined_groups": assessments, "coverage": coverage, "status": status,
            "tool_failures": tool_failures, "execution_trace": self.trace, "limitations": limitations})}

    def _build_graph(self):
        # Only graph wiring is specialized: all cognition/provider/tool/budget work
        # remains in the established runtime. Explicit typed routes expose limited exit.
        graph = StateGraph(InvestigationState)

        def observed(name, fn):
            async def node(state):
                self.record(name)
                answer = fn(state)
                if hasattr(answer, "__await__"):
                    answer = await answer
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
            {ValidationRoute.INSPECT: "investigate", ValidationRoute.FINALIZE: "review_findings",
             ValidationRoute.LIMITED_FINALIZE: "limited_review"})
        graph.add_edge("review_findings", "finalize")
        graph.add_edge("limited_review", "limited_finalize")
        graph.add_edge("finalize", END)
        graph.add_edge("limited_finalize", END)
        return graph.compile()


class ReuseOpportunityAgent(InvestigationAgent):
    request_type = ReuseOpportunityRequest
    config_type = ReuseOpportunityConfig
    execution_type = ReuseOpportunityExecution
    trace_name = "reuse-opportunity"
    agent_type = "reuse-opportunity"
