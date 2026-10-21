"""Evidence-grounded reuse research, sharing the existing investigator runtime."""

import json
from collections import Counter
from pathlib import Path

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from .....runtimes.investigation.agent import InvestigationExecution
from .....runtimes.investigation.provider import lean_schema
from .....runtimes.investigation.records import retain_previous
from .....runtimes.investigation.state import InvestigationState
from .....runtimes.invocation_reporting import report_invocation_phase
from .discovery import discover, source_characteristics
from .schemas import (
    ExaminedGroup,
    InspectRoute,
    ReuseEvaluation,
    ReuseFinding,
    ReuseOpportunityResult,
    ReusePlan,
    ReuseReview,
    ReuseToolFailure,
    ValidationRoute,
)


class ReuseOpportunityExecution(InvestigationExecution):
    trace_name = "reuse-opportunity"
    tool_prefix = "reuse-opportunity"
    prompt_directory = Path(__file__).parent / "prompts"
    evaluation_schema = ReuseEvaluation
    finding_schema = ReuseFinding
    result_schema = ReuseOpportunityResult
    plan_schema = ReusePlan
    review_schema = ReuseReview

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
        self.hypothesis_scopes = {}
        self.scope_issues = {}
        self._last_blocked_progress = None
        self.original_hypotheses = {}
        self.proposed_citations = {}
        self.hypothesis_validation_issues = {}

    @property
    def planned_groups(self):
        return set().union(*self.hypothesis_scopes.values()) if self.hypothesis_scopes else set()

    async def plan_investigation(self, state):
        update = await super().plan_investigation(state)
        if update["plan"]:
            admitted, committed = [], set()
            for hypothesis in update["plan"].hypotheses:
                ids = set(hypothesis.group_ids) & self.groups.keys()
                if len(committed | ids) > self.config.max_planned_groups:
                    self.issues.append(f"Deferred hypothesis {hypothesis.id}: initial max_planned_groups limit; no comparison committed for this question.")
                    continue
                admitted.append(hypothesis)
                committed.update(ids)
            update["plan"] = update["plan"].model_copy(update={"hypotheses": admitted})
            update["hypotheses"] = admitted
            self.original_hypotheses = {h.id: h for h in update["plan"].hypotheses}
            for hypothesis in update["plan"].hypotheses:
                ids = set(hypothesis.group_ids)
                self.hypothesis_scopes[hypothesis.id] = ids & self.groups.keys()
                if not ids or ids - self.groups.keys():
                    self.scope_issues[hypothesis.id] = "Declare exact selected group_ids for this hypothesis; unknown or empty binding."
            if self.groups and not update["plan"].hypotheses:
                self.scope_issues["plan"] = "Select a bounded group and hypothesis, or report why comparison cannot be planned."
        return update

    def structured_schema(self, schema):
        return lean_schema(schema) if isinstance(self.model, BaseChatModel) else schema

    def _context(self, state):
        context = super()._context(state) | {
            "quality_attribute": "reusability", "declaration_scope": self.request.targets,
            "candidate_groups": [g.model_dump() for g in self.coverage.selected_groups],
            "discovery_coverage": self.coverage.model_dump(exclude={"selected_groups"}),
            "candidate_queue": [g for g in sorted(self.planned_groups) if not state["evaluation"] or
                g not in {a.group_id for a in state["evaluation"].group_assessments}],
            "hypothesis_scopes": {key: sorted(value) for key, value in self.hypothesis_scopes.items()},
            "scope_issues": self.scope_issues,
            "max_planned_groups": self.config.max_planned_groups,
            "representation_scope": "Structural representations cover Python, TypeScript and JavaScript only; missing symbols or edges, including in these languages, do not establish absence of behavior or reuse opportunities.",
            "discovery_is_navigation_not_proof": True,
        }
        context["tool_error_feedback"] = [item.model_dump() for item in self.tool_failure_details(state)[-6:]]
        references = self.references()
        reads = []
        for identifier in sorted(self.planned_groups):
            for member in self.groups[identifier].members:
                cursor = member.start_line
                for record in sorted((r for r in references if r.kind == "source" and r.file_id == member.file_id),
                                     key=lambda r: r.start_line):
                    if record.start_line > cursor:
                        break
                    cursor = max(cursor, record.end_line + 1)
                if cursor <= member.end_line:
                    reads.append({"tool": "get_source_excerpt", "arguments": {"path": member.path,
                        "start_line": cursor, "end_line": min(member.end_line, cursor + self.tools.limits.max_source_lines - 1)}})
        context["next_source_reads"] = reads[:6]
        if state["evaluation"]:
            assessments = [self.normalize(a, {h.id for h in state["hypotheses"]}) for a in state["evaluation"].group_assessments]
            context["group_validation"] = [{"group_id": a.group_id, "validation_issues": a.validation_issues,
                "unknowns": a.unknowns, "qualification_notes": a.qualification_notes} for a in assessments]
            context["qualified_group_assessments"] = [a.model_dump() for a in assessments]
        return context

    def record(self, event):
        self.trace.append(event)
        self.logger.info("reuse_opportunity: %s", event)

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
        if not reason:
            reason = ("iteration_limit" if state["iterations"] >= self.config.max_iterations else
                      "tool_call_limit" if self.tools.budget_usage.tool_calls >= self.tool_limit else
                      "model_call_limit" if self.calls >= self.call_limit - self.closing_call_reserve else
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

    def resolve_citations(self, ids):
        """Only exact indexed anchors may alias delivered, commit-verified source."""
        references = {r.id: r for r in self.references()}
        resolved = []
        for identifier in ids:
            if identifier in references:
                resolved.append(identifier)
                continue
            anchor = self.anchors.get(identifier)
            if not anchor or anchor.start_line is None:
                continue
            records = [r for r in references.values() if r.kind == "source" and r.file_id == anchor.file_id
                and r.start_line <= (anchor.end_line or anchor.start_line) and r.end_line >= anchor.start_line]
            records, mismatch = self.verify_references(records)
            if not mismatch and self.covered(records, anchor.file_id, anchor.start_line, anchor.end_line or anchor.start_line):
                resolved.extend(r.id for r in records)
        return list(dict.fromkeys(resolved))

    def repair_evaluation(self, evaluation):
        for assessment in evaluation.group_assessments:
            self.proposed_citations[assessment.group_id] = {
                **{p.component_id: list(p.evidence_ids) for p in assessment.implementations},
                **{"caller:" + c.caller_id: list(c.evidence_ids) for c in assessment.callers}}
        assessments = [a.model_copy(update={
            "implementations": [p.model_copy(update={"evidence_ids": self.resolve_citations(p.evidence_ids)}) for p in a.implementations],
            "callers": [c.model_copy(update={"evidence_ids": self.resolve_citations(c.evidence_ids)}) for c in a.callers],
        }) for a in evaluation.group_assessments]
        return evaluation.model_copy(update={"group_assessments": assessments,
            "candidates": [c.model_copy(update={"evidence_ids": self.resolve_citations(c.evidence_ids)}) for c in evaluation.candidates],
            "hypotheses": [h.model_copy(update={"evidence_ids": self.resolve_citations(h.evidence_ids)}) for h in evaluation.hypotheses]})

    def normalize(self, assessment, hypotheses):
        proposed = {p.component_id: list(p.evidence_ids) for p in assessment.implementations}
        proposed.update({"caller:" + c.caller_id: list(c.evidence_ids) for c in assessment.callers})
        proposed = self.proposed_citations.get(assessment.group_id, proposed)
        assessment = assessment.model_copy(update={
            "implementations": [p.model_copy(update={"evidence_ids": self.resolve_citations(p.evidence_ids)}) for p in assessment.implementations],
            "callers": [c.model_copy(update={"evidence_ids": self.resolve_citations(c.evidence_ids)}) for c in assessment.callers]})
        group = self.groups.get(assessment.group_id)
        ids = [i for p in assessment.implementations for i in p.evidence_ids]
        ids.extend(i for c in assessment.callers for i in c.evidence_ids)
        references = {r.id: r for r in self.references()}
        records, mismatch = self.verify_references([references[i] for i in dict.fromkeys(ids) if i in references])
        issues = []
        if any(not self.resolve_citations([i]) for values in proposed.values() for i in values):
            issues.append("unknown_evidence_ids")
        if mismatch:
            issues.append("commit_mismatch")
        if not group:
            issues.append("unknown_or_out_of_scope_group")
        if assessment.group_id in self.duplicate_groups:
            issues.append("duplicate_group_assessment")
        if assessment.hypothesis_id not in hypotheses:
            issues.append("unknown_hypothesis")
        if assessment.group_id not in self.hypothesis_scopes.get(assessment.hypothesis_id, set()):
            issues.append("group_outside_hypothesis_scope")
        members = {m.component_id: m for m in group.members} if group else {}
        if Counter(p.component_id for p in assessment.implementations) != Counter(members.keys()):
            issues.append("group_requires_distinct_selected_implementations")
        profiles = []
        contract_members = []
        for profile in assessment.implementations:
            member = members.get(profile.component_id)
            own = [r for r in records if r.id in profile.evidence_ids]
            if not member or not self.covered(own, member.file_id, member.start_line, member.end_line):
                issues.append("implementation_body_not_inspected:" + profile.component_id)
            if not all(value.strip() for key, value in profile.model_dump().items()
                       if key not in {"evidence_ids", "component_id"}):
                issues.append("empty_behavior_comparison")
            symbol = self.symbols.get(profile.component_id)
            contract = symbol and source_characteristics(symbol, self.files[symbol.file_id], self.symbols)[0]
            if contract or profile.behavior_basis == "contract_only":
                contract_members.append(profile.component_id)
                issues.append("contract_declaration_does_not_establish_implementation_behavior:" + profile.component_id)
                profile = profile.model_copy(update={"behavior_basis": "contract_only",
                    "failure_behavior": "Unknown from contract declaration. Unverified model interpretation: " + profile.failure_behavior,
                    "side_effects": "Unknown from contract declaration. Unverified model interpretation: " + profile.side_effects})
            profiles.append(profile)
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
        unknowns = list(assessment.unknowns)
        qualifications = []
        if assessment.classification == "conditional":
            qualifications.append("Conditional source-backed observation only; extraction safety and migration effort are not established by body similarity.")
            uninspected = sorted(set(members) - inspected_callers)
            if uninspected:
                note = "Caller compatibility and migration effects remain unverified for: " + ", ".join(uninspected)
                qualifications.append(note)
                if len(unknowns) < 16 and note not in unknowns:
                    unknowns.append(note)
        if contract_members:
            unknowns.append("Implementation behavior, side effects and failure semantics were not established for contract-only members: " + ", ".join(contract_members))
        return ExaminedGroup(**assessment.model_dump(exclude={"implementations", "unknowns"}),
            implementations=profiles, unknowns=unknowns, qualification_notes=qualifications,
            proposed_evidence_ids=proposed, members=list(members.values()), evidence=records,
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

    def tool_failure_details(self, state):
        """Correlate provider and repository IDs so one error is reported once."""
        failures = {}
        calls = {}
        for message in state["messages"]:
            if isinstance(message, AIMessage):
                calls.update({call["id"]: call for call in message.tool_calls})
                continue
            if not isinstance(message, ToolMessage):
                continue
            failed = message.status == "error"
            payload = {}
            if isinstance(message.content, str):
                try:
                    decoded = json.loads(message.content)
                    payload = decoded if isinstance(decoded, dict) else {}
                    failed |= payload.get("status") == "error"
                except ValueError:
                    pass
            if failed:
                call = calls.get(message.tool_call_id, {})
                args = call.get("args", {})
                error_value = payload.get("error")
                error = error_value if isinstance(error_value, dict) else {"code": str(error_value)} if error_value else {}
                identifier = payload.get("tool_call_id", message.tool_call_id)
                failures[identifier] = ReuseToolFailure(tool=payload.get("tool_name") or message.name or call.get("name", "unknown"),
                    call_id=identifier, provider_call_id=message.tool_call_id,
                    stage="repository" if payload.get("tool_call_id") else "tool_node",
                    code=str(error.get("code", "tool_argument_or_execution_error")),
                    message=str(error.get("message") or message.content)[:1000],
                    path=args.get("path") if isinstance(args.get("path"), str) else None,
                    start_line=args.get("start_line") if type(args.get("start_line")) is int else None,
                    end_line=args.get("end_line") if type(args.get("end_line")) is int else None)
        for measurement in self.tools.tool_measurements:
            if measurement.status != "ok" and measurement.call_id not in failures:
                failures[measurement.call_id] = ReuseToolFailure(tool=measurement.tool, call_id=measurement.call_id,
                    stage="repository", code="repository_tool_error", message="Error recorded in repository ledger; response unavailable.")
        return list(failures.values())

    def tool_failures(self, state):
        return [f"{failure.tool}:{failure.call_id}:error" for failure in self.tool_failure_details(state)]

    def sharing_resolution_issues(self, judgment, linked, review, candidates):
        """Check proposal coherence without treating any rejection as a negative answer."""
        if judgment.resolution == "inconclusive":
            return ["sharing_feasibility_unresolved"]
        expected = judgment.resolution == "confirmed"
        if judgment.sharing_supported is not expected:
            return ["resolution_does_not_answer_sharing_feasibility"]
        supported = set(judgment.supporting_group_ids)
        linked_ids = {a.group_id for a in linked}
        reviews = {r.finding_id: r for r in review.findings}
        positive = [c for c in candidates if c.group_id in linked_ids and c.classification != "not_recommended"]
        by_id = {a.group_id: a for a in linked}
        accepted = {c.group_id for c in positive if c.id in reviews and reviews[c.id].status == "accepted"
            and not self.finding_issues(c, by_id)}
        if not expected:
            return ["discarded_hypothesis_has_supported_sharing_proposal"] if supported or accepted else []
        if not supported or not judgment.supported_boundary.strip() or not supported <= linked_ids:
            return ["confirmed_requires_concrete_assessed_sharing_boundary"]
        issues = []
        for identifier in supported:
            assessment = next(a for a in linked if a.group_id == identifier)
            if assessment.classification == "not_recommended":
                issues.append("confirmed_uses_not_recommended_group:" + identifier)
            proposals = [c for c in positive if c.group_id == identifier]
            if not proposals or identifier not in accepted:
                issues.append("confirmed_requires_supported_reviewed_proposal:" + identifier)
        return issues

    def validate_hypotheses(self, hypotheses, assessments, review=None, candidates=()):
        references = {r.id: r for r in self.references()}
        validated = []
        for hypothesis in hypotheses:
            original = self.original_hypotheses.get(hypothesis.id)
            if original:
                hypothesis = hypothesis.model_copy(update={"question": original.question,
                    "criterion_id": original.criterion_id, "evidence_needed": original.evidence_needed})
            scope = self.hypothesis_scopes.get(hypothesis.id, set())
            linked = [a for a in assessments if a.hypothesis_id == hypothesis.id and a.group_id in scope]
            valid = (bool(scope) and hypothesis.id not in self.scope_issues
                and {a.group_id for a in linked} == scope and all(not a.validation_issues for a in linked))
            if review is not None:
                matches = [j for j in review.hypotheses if j.hypothesis_id == hypothesis.id]
                judgment = matches[0] if len(matches) == 1 else None
                required = {r.id for a in linked for r in a.evidence} | set(hypothesis.evidence_ids)
                valid = (valid and judgment and judgment.scope_supported and not judgment.unverified_claims
                    and judgment.resolution in {"confirmed", "discarded"}
                    and set(judgment.assessment_group_ids) == scope
                    and len(judgment.assessment_group_ids) == len(scope)
                    and required and required <= set(judgment.checked_evidence_ids)
                    and set(judgment.checked_evidence_ids) <= references.keys()
                    and not self.evidence_issues(list(required), references)[1])
                semantic_issues = self.sharing_resolution_issues(judgment, linked, review, candidates) if judgment else ["independent_hypothesis_review_missing"]
                if not valid:
                    semantic_issues.append("planned_comparison_or_scope_review_incomplete")
                self.hypothesis_validation_issues[hypothesis.id] = semantic_issues
                valid = valid and not semantic_issues
                if valid:
                    hypothesis = hypothesis.model_copy(update={"status": judgment.resolution, "rationale": judgment.rationale,
                        "evidence_ids": sorted(required)})
            if not valid and (review is not None or hypothesis.status in {"confirmed", "discarded"}):
                hypothesis = hypothesis.model_copy(update={"status": "inconclusive", "rationale":
                    "Unverified model interpretation: " + hypothesis.rationale +
                    "\nHost validation: planned group behavior or independent scope review is incomplete. " +
                    ", ".join(self.hypothesis_validation_issues.get(hypothesis.id, []))})
            validated.append(hypothesis)
        return validated

    async def evaluate_evidence(self, state):
        references, mismatch = self.verify_references(self.references())
        ready = {identifier for identifier in self.planned_groups if all(
            self.covered(references, m.file_id, m.start_line, m.end_line) for m in self.groups[identifier].members)}
        if self.planned_groups and (not ready or mismatch):
            # Do not pay for a semantic comparison when no pair has been read.
            gaps = ["Read both complete implementation bodies before evaluating planned group " + i
                    for i in sorted(self.planned_groups - ready)]
            if mismatch:
                self.provenance_blocked = True
                gaps.append("Resolve commit provenance before evaluating implementation behavior.")
            current = state["evaluation"] or ReuseEvaluation(sufficient=False, hypotheses=state["hypotheses"],
                candidates=[], group_assessments=[], missing_information=[])
            update = {"evaluation": current.model_copy(update={"sufficient": False, "missing_information": gaps}),
                "hypotheses": state["hypotheses"], "missing_information": gaps,
                "iterations": state["iterations"] + 1, "model_calls": self.calls,
                "tool_calls": self.tools.budget_usage.tool_calls, "evidence": references}
        else:
            raw = await self.call("evaluate_evidence", state, self.evaluation_schema)
            current = self.repair_evaluation(raw) if raw else state["evaluation"]
            if raw:
                gaps = self.evaluation_evidence_gaps(current)
                current = current.model_copy(update={"sufficient": current.sufficient and not gaps,
                    "missing_information": list(dict.fromkeys([*current.missing_information, *gaps]))})
            update = {"evaluation": current, "hypotheses": current.hypotheses if current else state["hypotheses"],
                "missing_information": current.missing_information if current else ["A valid evidence evaluation could not be completed."],
                "iterations": state["iterations"] + 1, "model_calls": self.calls,
                "tool_calls": self.tools.budget_usage.tool_calls, "evidence": self.references()}
        current = update["evaluation"]
        if current is None:
            return update
        counts = Counter(a.group_id for a in current.group_assessments)
        self.duplicate_groups.difference_update(counts)
        self.duplicate_groups.update(i for i, count in counts.items() if count > 1)
        prior = state["evaluation"]
        if prior is not None:
            current = current.model_copy(update={
                "group_assessments": retain_previous(current.group_assessments, prior.group_assessments, identity="group_id"),
                "candidates": retain_previous(current.candidates, prior.candidates),
            })
        assessed = [self.normalize(a, {h.id for h in update["hypotheses"]}) for a in current.group_assessments]
        hypotheses = self.validate_hypotheses(update["hypotheses"], assessed)
        update["hypotheses"] = hypotheses
        current = current.model_copy(update={"hypotheses": hypotheses})
        by_id = {a.group_id: a for a in assessed}
        gaps = list(current.missing_information)
        if len(current.group_assessments) > self.config.max_groups:
            gaps.append("Group assessment count exceeds the configured max_groups budget.")
        for a in assessed:
            if a.validation_issues and a.group_id in self.hypothesis_scopes.get(a.hypothesis_id, set()):
                gaps.append("Resolve group " + a.group_id + ": " + ", ".join(a.validation_issues))
        for identifier in sorted(self.planned_groups - by_id.keys()):
            gaps.append("Inspect planned group " + identifier + " or report why comparison is blocked.")
        gaps.extend(f"Hypothesis {identifier}: {issue}" for identifier, issue in self.scope_issues.items())
        for c in current.candidates:
            if self.finding_issues(c, by_id):
                gaps.append("Resolve candidate " + c.id + ": behavior comparison, classification, components or citations are unsupported.")
        for h in update["hypotheses"]:
            if h.status in {"pending", "inconclusive"}:
                gaps.append("Resolve hypothesis " + h.id + " or identify a specific evidence blocker.")
        update["evaluation"] = current.model_copy(update={"sufficient": current.sufficient and not gaps,
            "missing_information": list(dict.fromkeys(gaps))})
        update["missing_information"] = update["evaluation"].missing_information
        blocked = [a for a in assessed if a.validation_issues and a.group_id in self.planned_groups]
        if blocked:
            files = {m.file_id for a in blocked for m in a.members} | {r.file_id for a in blocked for r in a.evidence}
            progress = json.dumps({"issues": sorted((a.group_id, a.validation_issues) for a in blocked),
                "source": sorted((r.file_id, r.start_line, r.end_line) for r in self.references()
                                 if r.kind == "source" and r.file_id in files)})
            if progress == self._last_blocked_progress and not self.stop:
                self.stop = "no_investigation_progress"
                self.issues.append("Reuse comparison made no relevant source/validation progress; stopped exploration to preserve review.")
            self._last_blocked_progress = progress
        else:
            self._last_blocked_progress = None
        return update

    def finalize(self, state):
        result = super().finalize(state)["result"]
        evaluation = state["evaluation"]
        assessments = [self.normalize(a, {h.id for h in result.hypotheses}) for a in evaluation.group_assessments] if evaluation else []
        by_id = {a.group_id: a for a in assessments}
        review = state["review"] if isinstance(state["review"], ReuseReview) else None
        hypotheses = self.validate_hypotheses(result.hypotheses, assessments, review or ReuseReview(findings=[]),
            evaluation.candidates if evaluation else ())
        missing = list(result.missing_information)
        for hypothesis in hypotheses:
            if hypothesis.status in {"pending", "inconclusive"}:
                missing.append(f"Hypothesis {hypothesis.id}: complete planned comparisons and independent scope review.")
            else:
                prefixes = (f"Resolve hypothesis {hypothesis.id} or identify a specific evidence blocker.",
                    f"Resolve hypothesis {hypothesis.id} with source evidence or explain its concrete blocker:")
                missing = [gap for gap in missing if not gap.startswith(prefixes)]
        resolved = {h.id for h in hypotheses if h.status in {"confirmed", "discarded"}}
        findings = []
        seen = {}
        for finding in result.findings:
            assessment = by_id.get(finding.group_id)
            if (self.finding_issues(finding, by_id) or assessment and assessment.hypothesis_id not in resolved) and finding.validation_status != "rejected":
                finding = finding.model_copy(update={"validation_status": "insufficient_evidence", "confidence": 0,
                    "review_rationale": "Host validation requires both source implementations, behavior/tradeoff analysis, matching classification and citations; recommended reuse also requires inspected callers and no unresolved unknowns."})
            finding = finding.model_copy(update={"stable_id": "REUSE-" + finding.group_id.removeprefix("ROG-")})
            if assessment:
                finding = finding.model_copy(update={"sharing_boundary": assessment.proposed_boundary, "unknowns": assessment.unknowns})
            if finding.classification == "conditional" and assessment:
                conditions = list(dict.fromkeys([*assessment.conditions, *assessment.unknowns,
                    "Verify the proposed boundary preserves each member's return/error contracts, mutation ownership and resource cleanup.",
                    "Validate consumer compatibility before extraction; benefit and migration effort remain qualitative."]))
                finding = finding.model_copy(update={"conditions": conditions,
                    "review_rationale": finding.review_rationale + "\nHost qualification: " + " ".join(assessment.qualification_notes),
                    "recommendation": "Conditional proposal; verify these conditions before extraction. " + finding.recommendation +
                        "\nConditions: " + " ".join(conditions)})
            if finding.classification == "not_recommended":
                finding = finding.model_copy(update={"severity": "info"})
            if finding.validation_status == "accepted":
                if finding.group_id in seen:
                    finding = finding.model_copy(update={"duplicate_of": seen[finding.group_id], "validation_status": "rejected",
                        "confidence": 0, "review_rationale": "Duplicate group conclusion retained for traceability; see " + seen[finding.group_id]})
                else:
                    seen[finding.group_id] = finding.id
            findings.append(finding)
        pending = sorted(self.planned_groups - {a.group_id for a in assessments if not a.validation_issues})
        tool_failures = self.tool_failures(state)
        complete = (not self.limited and result.termination_reason == "sufficient_evidence" and result.plan is not None
            and state["review"] is not None and not pending and not missing and not tool_failures and not self.scope_issues
            and not any(f.validation_status == "insufficient_evidence" for f in findings)
            and not any(h.status in {"pending", "inconclusive"} for h in hypotheses))
        status = "completed" if complete else "failed" if result.plan is None and not self.references() else "partial"
        coverage = self.coverage.model_copy(update={"unassessed_groups": pending,
            "planned_groups": sorted(self.planned_groups), "unplanned_groups": sorted(self.groups.keys() - self.planned_groups),
            "inspected_paths": sorted({r.path for r in self.references() if r.kind == "source"})})
        limitations = [*result.limitations,
            "Discovery is bounded static navigation, not a semantic equivalence or measured savings claim; no findings does not certify absence of opportunities.",
            "Caller links are static internal relationships, not proof of runtime dispatch. Missing/dynamic consumers constrain recommendations.",
            "Qualitative behavior, benefits and migration risks remain model judgments; accepted findings are proposals, never mandatory refactors."]
        limitations.append("Discovery selection is not committed coverage; unplanned groups remain unevaluated. Protocol signatures do not establish implementation behavior or absence of reuse opportunities.")
        limitations.append("Structural representations cover Python, TypeScript and JavaScript; other languages and unresolved or unindexed constructs remain outside structural coverage. Missing graph evidence does not certify absence of behavior or reuse opportunities.")
        if not any(h.status in {"pending", "inconclusive"} for h in hypotheses):
            limitations = [item for item in limitations if item != "Some hypotheses remain inconclusive; absence of findings does not establish boundary compliance."]
        limitations = [s.replace("boundary compliance", "absence of reuse opportunities") for s in limitations]
        return {"result": ReuseOpportunityResult.model_validate({**result.model_dump(), "findings": findings,
            "hypotheses": hypotheses, "critical_review": review, "missing_information": list(dict.fromkeys(missing)),
            "hypothesis_validation_issues": self.hypothesis_validation_issues,
            "termination_reason": "evidence_validation_failed" if not complete and result.termination_reason == "sufficient_evidence" else result.termination_reason,
            "examined_groups": assessments, "coverage": coverage, "status": status,
            "tool_failures": tool_failures, "tool_failure_details": self.tool_failure_details(state),
            "execution_trace": self.trace, "limitations": limitations})}

    def _build_graph(self):
        # Only graph wiring is specialized: all cognition/provider/tool/budget work
        # remains in the established runtime. Explicit typed routes expose limited exit.
        graph = StateGraph(InvestigationState)

        def observed(name, fn):
            async def node(state):
                await report_invocation_phase(name)
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
        graph.add_conditional_edges("plan_investigation", self.route_plan,
            {"investigate": "investigate", "finalize": "limited_finalize"})
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


