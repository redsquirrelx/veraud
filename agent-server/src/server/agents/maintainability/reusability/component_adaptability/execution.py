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

from .....runtimes.investigation.agent import InvestigationExecution
from .....runtimes.investigation.provider import lean_schema
from .....runtimes.investigation.records import retain_previous
from .....runtimes.investigation.state import InvestigationState
from .....runtimes.repository.tools import TOOL_SCHEMAS
from .discovery import discover
from .schemas import (
    AdaptabilityEvaluation,
    AdaptabilityFinding,
    AdaptabilityPlan,
    AdaptabilityReview,
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
    plan_schema = AdaptabilityPlan
    review_schema = AdaptabilityReview

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
        self.hypothesis_scopes, self.original_hypotheses, self.scope_issues = {}, {}, {}
        self.hypothesis_validation_issues = {}
        self.actionable = False
        self._last_blocked_progress = None
        self._repair_reads_attempted = set()
        self.candidate_split_history = {}
        self.model_hypothesis_rationales = {}

    @property
    def planned_components(self):
        return set().union(*self.hypothesis_scopes.values()) if self.hypothesis_scopes else set()

    async def plan_investigation(self, state):
        update = await super().plan_investigation(state)
        if update["plan"]:
            for hypothesis in update["plan"].hypotheses:
                self.original_hypotheses[hypothesis.id] = hypothesis
                ids = set(hypothesis.component_ids)
                self.hypothesis_scopes[hypothesis.id] = ids & self.components.keys()
                if not ids or ids - self.components.keys():
                    self.scope_issues[hypothesis.id] = "Bind exact selected component_ids; empty or unknown component binding."
            if self.components and not update["plan"].hypotheses:
                self.scope_issues["plan"] = "A bounded component investigation must be planned before drawing conclusions."
        return update

    def structured_schema(self, schema):
        return lean_schema(schema) if isinstance(self.model, BaseChatModel) else schema

    async def call(self, node, state, schema=None):
        self.context_node = node
        return await super().call(node, state, schema)

    def _context(self, state):
        context = super()._context(state) | {
            "quality_attribute": "reusability", "target_context": self.request.target_context,
            "component_scope": self.request.targets,
            "selected_components": [c.model_dump() for c in self.coverage.selected_components],
            "discovery_coverage": self.coverage.model_dump(exclude={"selected_components"}),
            "available_tools": self.config.tools,
            "allowed_tool_argument_schemas": {name: TOOL_SCHEMAS[name].model_json_schema() for name in self.config.tools}
                if self.context_node == "investigate" else {},
            "visited_symbols": sorted({s for r in self.references() for s in r.symbol_ids}),
            "discovery_is_navigation_not_evidence": True,
            "hypothesis_scopes": {key: sorted(value) for key, value in self.hypothesis_scopes.items()},
            "scope_issues": self.scope_issues,
            "representation_scope": "Structural representations cover Python, TypeScript and JavaScript only; configuration and fixture source can be read as auxiliary evidence, not structural proof of production behavior.",
        }
        reads = self.pending_source_reads()
        context["next_source_reads"] = reads[:6]
        if state["evaluation"]:
            assessments = [self.normalize(a, {h.id for h in state["hypotheses"]}) for a in state["evaluation"].constraint_assessments]
            context["constraint_validation"] = [a.model_dump() for a in assessments]
            context["candidate_validation"] = {c.id: self.candidate_issues(c, {a.id: a for a in assessments}) for c in state["evaluation"].candidates}
        return context

    def pending_source_reads(self):
        references = self.references()
        reads = []
        for identifier in sorted(self.planned_components):
            component = self.components[identifier]
            cursor = component.start_line
            for record in sorted((r for r in references if r.kind == "source" and r.file_id == component.file_id), key=lambda r: r.start_line):
                if record.start_line > cursor:
                    break
                cursor = max(cursor, record.end_line + 1)
            if cursor <= component.end_line:
                end = min(component.end_line, cursor + self.tools.limits.max_source_lines - 1)
                lines = self.files[component.file_id].content.splitlines()
                while end >= cursor and len("\n".join(lines[cursor - 1:end])) > self.tools.limits.max_source_characters:
                    end -= 1
                if end < cursor:
                    continue  # A single overlong line cannot be safely read with these limits.
                reads.append({"name": "get_source_excerpt", "arguments": {"path": component.path, "start_line": cursor,
                    "end_line": end}})
        return reads

    async def investigate(self, state):
        # Explicit structured decisions replace the legacy free-text "ready" response.
        if self.calls >= self.call_limit - self.closing_call_reserve or self.tools.budget_usage.tool_calls >= self.tool_limit:
            return {"messages": [AIMessage(content="", tool_calls=[])], "model_calls": self.calls}
        if state["evaluation"] is not None and not self.stop and self.remaining_seconds() > 0 and "get_source_excerpt" in self.config.tools:
            calls = []
            remaining = self.tool_limit - self.tools.budget_usage.tool_calls
            for read in self.pending_source_reads():
                signature = json.dumps(read, sort_keys=True)
                if signature in self._repair_reads_attempted:
                    continue
                self._repair_reads_attempted.add(signature)
                calls.append({"name": read["name"], "args": read["arguments"], "id": "repair-" + uuid4().hex})
                if len(calls) >= remaining:
                    break
            if calls:
                self.record("repair:complete_component_bodies")
                return {"messages": [AIMessage(content="", tool_calls=calls)], "model_calls": self.calls}
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
        reason = self.stop or ("provenance_unverifiable" if self.provenance_blocked else "")
        if not reason and self.remaining_seconds() <= 0:
            reason = "time_limit"
        if not reason and evaluation and evaluation.sufficient and not evaluation.missing_information:
            reason = "sufficient_evidence"
        if not reason and evaluation and not evaluation.can_investigate_further and not self.actionable and evaluation.continuation_blocker != "none":
            reason = "unverifiable"
        if not reason:
            reason = ("iteration_limit" if state["iterations"] >= self.config.max_iterations else
                      "tool_call_limit" if self.tools.budget_usage.tool_calls >= self.tool_limit else
                      "model_call_limit" if self.calls >= self.call_limit - self.closing_call_reserve else
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
        # Supporting citations identify the claim; body coverage also includes delivered
        # continuations. A model repeating its initial citation must not hide tool reads.
        # Require an original source citation to this component, not just metadata.
        body_ids = []
        if component and any(i in references and references[i].kind == "source"
                and references[i].file_id == component.file_id
                and references[i].start_line <= component.end_line
                and references[i].end_line >= component.start_line for i in assessment.supporting_evidence_ids):
            body_ids = [r.id for r in references.values() if r.kind == "source" and r.file_id == component.file_id
                and r.start_line <= component.end_line and r.end_line >= component.start_line]
        ids.extend(body_ids)
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
        if assessment.component_id not in self.hypothesis_scopes.get(assessment.hypothesis_id, set()):
            issues.append("component_outside_hypothesis_scope")
        own = [r for r in evidence if r.id in body_ids]
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
        if assessment.constraint_type == "data_schema" and assessment.conclusion != "unknown":
            if assessment.schema_dependency_basis in {"unknown", "fixture_only"}:
                issues.append("schema_contract_or_domain_dependency_not_established")
            if not assessment.schema_adaptation_analysis.strip():
                issues.append("explain_schema_mismatch_and_existing_mapping_seams")
            if (assessment.schema_dependency_basis == "input_contract"
                and assessment.conclusion in {"verified_obstacle", "context_dependent_risk"} and not assessment.usage):
                issues.append("input_contract_requires_input_preparation_inspection")
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

    def split_candidates(self, evaluation):
        assessments = {a.id: a for a in evaluation.constraint_assessments}
        candidates = {}
        submitted = {c.id for c in evaluation.candidates if not c.split_from}
        for candidate in evaluation.candidates:
            if candidate.split_from in submitted:
                continue  # The resubmitted parent is rebuilt from current assessments.
            linked = [assessments[i] for i in candidate.assessment_ids if i in assessments]
            groups = {}
            for assessment in linked:
                key = (assessment.constraint_type, assessment.constraint_key.strip().casefold(),
                    assessment.assessed_context, assessment.conclusion)
                groups.setdefault(key, []).append(assessment)
            if len(groups) <= 1 or len(linked) != len(set(candidate.assessment_ids)) or any(
                a.conclusion not in {"verified_obstacle", "context_dependent_risk"} for a in linked):
                candidates[candidate.id] = candidate
                continue
            self.candidate_split_history[candidate.id] = candidate
            for key, members in groups.items():
                identifier = candidate.id + "-" + hashlib.sha256(json.dumps(key).encode()).hexdigest()[:12]
                # Rebuild scoped prose from the assessments, not the original mixed claim.
                candidates[identifier] = candidate.model_copy(update={"id": identifier, "split_from": candidate.id,
                    "assessment_ids": [a.id for a in members], "components": list(dict.fromkeys(a.component_id for a in members)),
                    "constraint_type": key[0], "classification": key[3],
                    "title": "Context-qualified constraint: " + members[0].constraint_key,
                    "description": "\n".join(fact for a in members for fact in a.observed_facts),
                    "justification": "\n".join(a.counterevidence_analysis for a in members),
                    "modularity_impact": "\n".join(a.adaptation_impact for a in members),
                    "recommendation": "\n".join(dict.fromkeys(option for a in members for option in a.mitigation_options)),
                    "evidence_ids": list(dict.fromkeys(i for a in members for i in [*a.supporting_evidence_ids,
                        *a.counterevidence_ids, *a.seam_evidence_ids, *[i for u in a.usage for i in u.evidence_ids]]))})
        return evaluation.model_copy(update={"candidates": list(candidates.values()), "missing_information": [gap
            for gap in evaluation.missing_information if not any(gap.startswith("Resolve candidate " + identifier + ":")
                for identifier in self.candidate_split_history)]})

    def candidate_issues(self, candidate, assessments):
        linked = [assessments[i] for i in candidate.assessment_ids if i in assessments]
        issues = []
        if not linked or len(linked) != len(set(candidate.assessment_ids)) or len(candidate.assessment_ids) != len(set(candidate.assessment_ids)):
            issues.append("unknown_or_duplicate_assessment_ids")
        keys = {(a.constraint_type, a.constraint_key.strip().casefold(), a.assessed_context) for a in linked}
        if len(keys) != 1:
            issues.append("inconsistent_constraint_keys_or_contexts")
        if candidate.kind != "design_observation":
            issues.append("adaptability_requires_design_observation")
        for assessment in linked:
            issues.extend(f"assessment:{assessment.id}:{issue}" for issue in assessment.validation_issues)
            if assessment.conclusion != candidate.classification or assessment.constraint_type != candidate.constraint_type:
                issues.append("assessment_classification_or_type_mismatch:" + assessment.id)
        if set(candidate.components) != {a.component_id for a in linked}:
            issues.append("candidate_components_do_not_match_assessments")
        if not {r.id for a in linked for r in a.evidence} <= set(candidate.evidence_ids):
            issues.append("assessment_citations_missing_from_candidate")
        if not set(candidate.evidence_ids) <= {r.id for r in self.references()}:
            issues.append("unknown_candidate_evidence_ids")
        return list(dict.fromkeys(issues))

    def unassessed(self, evaluation, assessments):
        complete = {a.component_id for a in assessments if not a.validation_issues and a.conclusion != "unknown"}
        if evaluation:
            # An empty result must still inspect the component, not merely its name.
            for identifier in evaluation.cleared_components:
                c = self.components.get(identifier)
                if c and self.covered(self.references(), c.file_id, c.start_line, c.end_line):
                    complete.add(identifier)
        return sorted(self.planned_components - complete)

    def validate_hypotheses(self, hypotheses, assessments, evaluation, review=None):
        validated = []
        references = {r.id: r for r in self.references()}
        for hypothesis in hypotheses:
            original = self.original_hypotheses.get(hypothesis.id)
            if original:
                hypothesis = hypothesis.model_copy(update={"question": original.question,
                    "criterion_id": original.criterion_id, "evidence_needed": original.evidence_needed})
            scope = self.hypothesis_scopes.get(hypothesis.id, set())
            linked = [a for a in assessments if a.hypothesis_id == hypothesis.id and a.component_id in scope]
            issues = []
            if not scope or hypothesis.id in self.scope_issues:
                issues.append("invalid_hypothesis_component_binding")
            complete = {a.component_id for a in linked if not a.validation_issues and a.conclusion != "unknown"}
            cleared = set(evaluation.cleared_components) & scope if evaluation else set()
            cleared = {i for i in cleared if self.covered(self.references(), self.components[i].file_id,
                self.components[i].start_line, self.components[i].end_line)}
            if scope - (complete | cleared) or any(a.validation_issues for a in linked):
                issues.append("committed_components_not_validly_assessed")
            required = {r.id for a in linked for r in a.evidence}
            required.update(r.id for r in self.references() if r.kind == "source" and any(
                self.components[i].file_id == r.file_id and r.start_line <= self.components[i].end_line
                and r.end_line >= self.components[i].start_line for i in cleared))
            if hypothesis.status == "confirmed" and not any(a.conclusion in {"verified_obstacle", "context_dependent_risk"} for a in linked):
                issues.append("confirmed_requires_context_qualified_constraint")
            if review is not None:
                judgments = [j for j in review.hypotheses if j.hypothesis_id == hypothesis.id]
                judgment = judgments[0] if len(judgments) == 1 else None
                if (not judgment or not judgment.scope_supported or judgment.unverified_claims
                    or judgment.resolution not in {"confirmed", "discarded"}
                    or set(judgment.assessment_ids) != {a.id for a in linked}
                    or not required or not required <= set(judgment.checked_evidence_ids)
                    or not set(judgment.checked_evidence_ids) <= references.keys()
                    or self.evidence_issues(list(required), references)[1]):
                    issues.append("independent_scope_review_incomplete")
                elif any(a.constraint_type == "data_schema" for a in linked) and not judgment.contract_and_fixture_claims_supported:
                    issues.append("input_contract_and_fixture_interpretation_not_verified")
                if judgment:
                    for assessment in linked:
                        if assessment.conclusion not in {"verified_obstacle", "context_dependent_risk"} or judgment.resolution != "confirmed":
                            continue
                        checks = [c for c in review.adaptation_checks if c.assessment_id == assessment.id]
                        check = checks[0] if len(checks) == 1 else None
                        evidence_ids = {r.id for r in assessment.evidence}
                        if (not check or not check.target_mismatch_supported
                            or not all(text.strip() for text in (check.required_change, check.existing_seams, check.why_seams_insufficient))
                            or not evidence_ids <= set(check.checked_evidence_ids)
                            or not set(check.checked_evidence_ids) <= references.keys()):
                            issues.append("concrete_adaptation_mismatch_not_reviewed:" + assessment.id)
                        elif assessment.constraint_type == "data_schema" and assessment.schema_dependency_basis == "input_contract" and check.input_normalization_suffices is not False:
                            issues.append("input_contract_not_shown_to_require_component_change:" + assessment.id)
                        elif assessment.conclusion == "context_dependent_risk" and (check.change_scope == "unknown" or not check.qualified_impact.strip()):
                            issues.append("context_risk_requires_qualified_change_scope:" + assessment.id)
                    candidates = [c for c in evaluation.candidates if set(c.assessment_ids) & {a.id for a in linked}] if evaluation else []
                    reviews = {r.finding_id: r for r in review.findings}
                    accepted = [c for c in candidates if c.id in reviews and reviews[c.id].status == "accepted"
                        and not self.candidate_issues(c, {a.id: a for a in assessments})]
                    if judgment.resolution == "confirmed" and (not any(a.conclusion in {"verified_obstacle", "context_dependent_risk"} for a in linked)
                        or candidates and not accepted):
                        issues.append("confirmed_constraint_not_supported_by_review")
                    if judgment.resolution == "discarded" and accepted:
                        issues.append("discarded_hypothesis_has_accepted_obstacle")
                if not issues and judgment:
                    hypothesis = hypothesis.model_copy(update={"status": judgment.resolution,
                        "rationale": judgment.rationale, "evidence_ids": sorted(required)})
            self.hypothesis_validation_issues[hypothesis.id] = issues
            if issues and (review is not None or hypothesis.status in {"confirmed", "discarded"}):
                rationale = self.model_hypothesis_rationales.get(hypothesis.id, hypothesis.rationale)
                hypothesis = hypothesis.model_copy(update={"status": "inconclusive", "rationale":
                    "Unverified model interpretation: " + rationale + "\nHost validation: " + ", ".join(issues)})
            validated.append(hypothesis)
        return validated

    async def evaluate_evidence(self, state):
        update = await super().evaluate_evidence(state)
        current = update["evaluation"]
        if current is None:
            return update
        for hypothesis in current.hypotheses:
            if not hypothesis.rationale.startswith("Unverified model interpretation: "):
                self.model_hypothesis_rationales[hypothesis.id] = hypothesis.rationale
        counts = Counter(a.id for a in current.constraint_assessments)
        self.duplicate_assessments.difference_update(counts)
        self.duplicate_assessments.update(i for i, count in counts.items() if count > 1)
        prior = state["evaluation"]
        if prior:
            current = current.model_copy(update={
                "constraint_assessments": retain_previous(current.constraint_assessments, prior.constraint_assessments),
                "candidates": retain_previous(current.candidates, prior.candidates),
            })
        current = self.split_candidates(current)
        assessments = [self.normalize(a, {h.id for h in update["hypotheses"]}) for a in current.constraint_assessments]
        # Carry only host-attached body continuations into candidates. Missing original
        # claim/seam/usage citations remain validation errors. Independent review below
        # must explicitly check the full expanded evidence set before acceptance.
        supplemental = {}
        for original, assessed in zip(current.constraint_assessments, assessments):
            cited = {*original.supporting_evidence_ids, *original.counterevidence_ids, *original.seam_evidence_ids,
                *[i for usage in original.usage for i in usage.evidence_ids]}
            supplemental[original.id] = [r.id for r in assessed.evidence if r.id not in cited]
        current = current.model_copy(update={"candidates": [c.model_copy(update={"evidence_ids": list(dict.fromkeys([
            *c.evidence_ids, *[i for identifier in c.assessment_ids for i in supplemental.get(identifier, [])]]))})
            for c in current.candidates]})
        update["hypotheses"] = self.validate_hypotheses(update["hypotheses"], assessments, current)
        current = current.model_copy(update={"hypotheses": update["hypotheses"]})
        by_id = {a.id: a for a in assessments}
        gaps = list(current.missing_information)
        if len(assessments) > self.config.max_constraints:
            self.stop = "constraint_limit"
            gaps.append("Constraint assessment count exceeds max_constraints.")
        for a in assessments:
            if a.validation_issues or a.conclusion == "unknown":
                gaps.append("Resolve constraint " + a.id + ": " + ", ".join(a.validation_issues or a.unknowns or ["unverified obstacle"]))
        for c in current.candidates:
            issues = self.candidate_issues(c, by_id)
            if issues:
                gaps.append("Resolve candidate " + c.id + ": " + ", ".join(issues))
        for identifier in self.unassessed(current, assessments):
            gaps.append("Inspect component " + identifier + " or state the specific evidence blocker.")
        if set(current.cleared_components) - self.components.keys() or not current.coverage_rationale.strip():
            gaps.append("Coverage declarations must identify selected components and a concrete rationale.")
        gaps.extend("Resolve hypothesis " + h.id + " or state a specific blocker." for h in update["hypotheses"] if h.status in {"pending", "inconclusive"})
        gaps.extend(f"Hypothesis {identifier}: {issue}" for identifier, issue in self.scope_issues.items())
        missing_bodies = [i for i in self.planned_components if not self.covered(self.references(), self.components[i].file_id,
            self.components[i].start_line, self.components[i].end_line)]
        unevaluated = self.planned_components - {a.component_id for a in assessments} - set(current.cleared_components)
        self.actionable = bool(missing_bodies or unevaluated or self.scope_issues or any(a.validation_issues for a in assessments)
            or any(self.candidate_issues(c, by_id) for c in current.candidates))
        can_continue = current.can_investigate_further
        if gaps and not can_continue and (self.actionable or current.continuation_blocker == "none"):
            can_continue = True
            self.actionable = True
            self.issues.append("Host rejected unsupported investigation blocker; available source or validation repairs remain. Model reason: " + current.continuation_reason)
        update["evaluation"] = current.model_copy(update={"sufficient": current.sufficient and not gaps,
            "can_investigate_further": can_continue, "missing_information": list(dict.fromkeys(gaps))})
        update["missing_information"] = update["evaluation"].missing_information
        if self.actionable:
            progress = json.dumps({"missing": sorted(missing_bodies), "constraints": sorted((a.id, a.validation_issues) for a in assessments),
                "candidates": sorted((c.id, self.candidate_issues(c, by_id)) for c in current.candidates),
                "source": sorted((r.file_id, r.start_line, r.end_line) for r in self.references() if r.kind == "source")})
            if progress == self._last_blocked_progress and not self.stop:
                self.stop = "no_investigation_progress"
                self.issues.append("No relevant source or validation progress; preserved partial results for review.")
            self._last_blocked_progress = progress
        else:
            self._last_blocked_progress = None
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
        review = state["review"] if isinstance(state["review"], AdaptabilityReview) else None
        hypotheses = self.validate_hypotheses(result.hypotheses, assessments, evaluation, review or AdaptabilityReview(findings=[]))
        missing = list(result.missing_information)
        for hypothesis in hypotheses:
            if hypothesis.status in {"pending", "inconclusive"}:
                missing.append(f"Hypothesis {hypothesis.id}: " + ", ".join(self.hypothesis_validation_issues.get(hypothesis.id, [])))
            else:
                missing = [gap for gap in missing if gap != f"Resolve hypothesis {hypothesis.id} or state a specific blocker."]
        resolved = {h.id for h in hypotheses if h.status in {"confirmed", "discarded"}}
        findings, seen = [], {}
        for finding in result.findings:
            linked = [by_id[i] for i in finding.assessment_ids if i in by_id]
            issues = self.candidate_issues(finding, by_id)
            issues.extend("hypothesis_not_resolved:" + a.hypothesis_id for a in linked if a.hypothesis_id not in resolved)
            issues = list(dict.fromkeys(issues))
            finding = finding.model_copy(update={"validation_issues": list(dict.fromkeys(issues))})
            if issues and finding.validation_status != "rejected":
                finding = finding.model_copy(update={"validation_status": "insufficient_evidence", "confidence": 0,
                    "review_rationale": "Host validation failed: " + ", ".join(issues)})
            key = (finding.constraint_type, linked[0].constraint_key.strip().casefold() if linked else finding.id,
                   linked[0].assessed_context if linked else "")
            stable_id = "ADAPT-" + hashlib.sha256(json.dumps(key).encode()).hexdigest()[:16]
            finding = finding.model_copy(update={"stable_id": stable_id,
                "assessed_context": linked[0].assessed_context if linked else "",
                "adaptation_impact": "\n".join(dict.fromkeys(a.adaptation_impact for a in linked)),
                "adaptation_effort": "\n".join(dict.fromkeys(a.adaptation_effort for a in linked)),
                "assumptions": list(dict.fromkeys(s for a in linked for s in a.assumptions)),
                "mitigation_options": list(dict.fromkeys(s for a in linked for s in a.mitigation_options))})
            if finding.validation_status == "accepted" and finding.classification == "context_dependent_risk" and review:
                checks = [c for c in review.adaptation_checks if c.assessment_id in finding.assessment_ids]
                facts = list(dict.fromkeys(fact for a in linked for fact in a.observed_facts))
                contexts = list(dict.fromkeys(a.assessed_context for a in linked))
                impact = "\n".join(dict.fromkeys(c.qualified_impact for c in checks))
                recommendation = "\n".join(dict.fromkeys(c.qualified_recommendation for c in checks if c.qualified_recommendation.strip()))
                qualification = "Context-dependent observation for the assessed scenario: " + "; ".join(contexts) + ". "
                if self.request.target_context is None:
                    qualification += "This scenario is an assumption, not a declared reuse requirement. "
                if checks and all(c.change_scope == "content_only" for c in checks):
                    qualification += "The required adaptation concerns content; displayed tax/accounting examples do not establish executable calculation rules or a need for a complete rewrite. "
                finding = finding.model_copy(update={"description": qualification + "Observed facts: " + " ".join(facts),
                    "justification": qualification + impact, "modularity_impact": impact,
                    "adaptation_impact": impact, "recommendation": qualification + recommendation,
                    "review_rationale": qualification + "Reviewed local consequence: " + impact,
                    "mitigation_options": [c.qualified_recommendation for c in checks if c.qualified_recommendation.strip()]})
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
            and state["review"] is not None and not pending and not failures and not missing and not self.scope_issues
            and not any(a.validation_issues or a.conclusion == "unknown" for a in assessments)
            and not any(f.validation_status == "insufficient_evidence" for f in findings)
            and not any(h.status in {"pending", "inconclusive"} for h in hypotheses))
        status = "completed" if complete else "failed" if result.plan is None and not self.references() else "partial"
        coverage = self.coverage.model_copy(update={"unassessed_components": pending,
            "planned_components": sorted(self.planned_components), "unplanned_components": sorted(self.components.keys() - self.planned_components),
            "inspected_paths": sorted({r.path for r in self.references() if r.kind == "source"})})
        limitations = [s.replace("boundary compliance", "component adaptability") for s in result.limitations]
        if not any(h.status in {"pending", "inconclusive"} for h in hypotheses):
            limitations = [s for s in limitations if s != "Some hypotheses remain inconclusive; absence of findings does not establish component adaptability."]
        limitations.extend([
            "Structural representations cover Python, TypeScript and JavaScript; auxiliary configuration/fixtures are readable but do not establish production behavior or complete dependency coverage.",
            "Static discovery hints and valid citations do not prove runtime behavior, mandatory dependency use or absence of extension points.",
            "Adaptation effort is qualitative; findings are context-qualified observations, not automatic refactors or measured cost estimates.",
            "Coverage is selective; bounded tool transcripts can reach the shared context limit. No automatic history compaction is implemented."])
        if evaluation and not evaluation.can_investigate_further and self.final_reason == "unverifiable":
            limitations.append("Investigation blocker: " + evaluation.continuation_reason)
        if self.request.target_context is None:
            limitations.append("Target context was not specified; plausible contexts are assumptions, not user requirements.")
        return {"result": ComponentAdaptabilityResult.model_validate({**result.model_dump(), "status": status,
            "hypotheses": hypotheses, "critical_review": review, "hypothesis_validation_issues": self.hypothesis_validation_issues,
            "candidate_split_history": self.candidate_split_history,
            "missing_information": list(dict.fromkeys(missing)),
            "termination_reason": "evidence_validation_failed" if not complete and result.termination_reason == "sufficient_evidence" else result.termination_reason,
            "findings": findings, "examined_constraints": assessments, "target_context": self.request.target_context,
            "coverage": coverage, "tool_failures": failures, "execution_trace": self.trace,
            "summary": f"{len(self.planned_components) - len(pending)}/{len(self.planned_components)} planned components investigated; "
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
        graph.add_conditional_edges("plan_investigation", self.route_plan,
            {"investigate": "investigate", "finalize": "limited_finalize"})
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


