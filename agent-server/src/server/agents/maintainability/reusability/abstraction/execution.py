"""Independent reusability investigator using the existing native LangGraph runtime."""

import json
from collections import Counter
from pathlib import Path

from langchain_core.language_models.chat_models import BaseChatModel

from .....runtimes.investigation.agent import InvestigationExecution
from .....runtimes.investigation.messages import compact_tool_history
from .....runtimes.investigation.provider import lean_schema
from .....runtimes.investigation.records import retain_previous
from .discovery import discover
from .schemas import (
    AbstractionCoverage,
    AbstractionEvaluation,
    AbstractionFinding,
    AbstractionHypothesisValidation,
    AbstractionPlan,
    AbstractionResult,
    AbstractionReview,
    ComponentReference,
    InspectedParticipant,
    InvestigatedAbstraction,
)


class AbstractionExecution(InvestigationExecution):
    trace_name = "abstraction"
    tool_prefix = "abstraction"
    prompt_directory = Path(__file__).parent / "prompts"
    evaluation_schema = AbstractionEvaluation
    finding_schema = AbstractionFinding
    result_schema = AbstractionResult
    review_schema = AbstractionReview
    plan_schema = AbstractionPlan

    def __init__(self, model, config, tools, request):
        super().__init__(model, config, tools, request)
        snapshot = tools.accessible_snapshot
        self.selected, self.candidate_count = discover(snapshot, request, config.max_candidates)
        self.selected_ids = {c.component_id for c in self.selected}
        self.files = {f.id: f for f in snapshot.files}
        self.symbols = {s.id: s for s in snapshot.symbols}
        self.relationships = {r.id: r for r in snapshot.relationships}
        self.anchors = {e.id: e for e in snapshot.evidence}
        self.duplicate_assessments = set()
        self.final_reason = ""
        self._closing_budget_reserved = False
        self._last_blocked_progress = None
        self.hypothesis_scopes = {}
        self.scope_issues = {}
        self.hypothesis_validation_history = []

    @property
    def planned_ids(self):
        return set().union(*self.hypothesis_scopes.values()) if self.hypothesis_scopes else set()

    async def plan_investigation(self, state):
        update = await super().plan_investigation(state)
        plan = update["plan"]
        if plan is None:
            return update
        if not plan.hypotheses:
            self.scope_issues["plan"] = "Plan contains no scoped hypotheses."
        hypotheses = []
        for hypothesis in plan.hypotheses:
            resolved, unknown = set(), []
            for identifier in hypothesis.declaration_ids:
                matches = {c.component_id for c in self.selected if identifier in {
                    c.component_id, c.path, f"{c.path}:{c.symbol_name}"}}
                if matches:
                    resolved.update(matches)
                else:
                    unknown.append(identifier)
            self.hypothesis_scopes[hypothesis.id] = resolved
            if unknown or not resolved:
                self.scope_issues[hypothesis.id] = "Missing or unknown planned declaration identities: " + (", ".join(unknown) or "none supplied")
            hypotheses.append(hypothesis.model_copy(update={"declaration_ids": sorted(resolved)}))
        update["plan"] = plan.model_copy(update={"hypotheses": hypotheses})
        update["hypotheses"] = hypotheses
        return update

    def closing_token_reserve(self, node, request_reserve):
        reserve = (min(self.token_limit // 3, 2 * request_reserve) if node == "investigate"
                   else min(self.token_limit // 6, request_reserve) if node == "evaluate_evidence" else 0)
        if reserve and self.tokens + request_reserve + reserve > self.token_limit:
            self._closing_budget_reserved = True
        return reserve

    def can_review_stopped(self, state):
        return super().can_review_stopped(state) or (
            state["evaluation"] is not None and self._closing_budget_reserved and self.stop == "token_limit")

    def provider_history(self, state, messages, *, overhead_characters=0, node=None):
        pinned = {i for h in state["hypotheses"] for i in h.evidence_ids}
        if state["evaluation"]:
            pinned.update(i for c in state["evaluation"].candidates for i in c.evidence_ids)
            for assessment in state["evaluation"].abstraction_assessments:
                pinned.update([*assessment.supporting_evidence_ids, *assessment.counterevidence_ids])
                pinned.update(i for p in assessment.participants for i in p.evidence_ids)
        used = len(json.dumps([m.model_dump() for m in messages], default=str)) + overhead_characters
        return compact_tool_history(state["messages"], max(0, int(self.config.max_context_characters * 0.4) - used), pinned)

    def model_context(self, node, state):
        context = self._context(state)
        context["evidence"] = [{k: v for k, v in r.items() if k in {
            "id", "file_id", "path", "kind", "start_line", "end_line", "symbol_ids"}} for r in context["evidence"]]
        for key in ("plan", "evaluation"):
            if context[key]:
                context[key] = {k: v for k, v in context[key].items() if k != "hypotheses"}
        if node != "investigate":
            context.pop("inventory", None)
            context.pop("abstraction_navigation", None)
        context["closing_due_to_token_budget"] = self._closing_budget_reserved
        return context

    def _context(self, state):
        context = super()._context(state) | {
            "quality_attribute": "reusability", "declaration_scope": self.request.targets,
            "abstraction_candidates": [c.model_dump() for c in self.selected],
            "discovery": {"candidate_count": self.candidate_count,
                          "omitted_candidates": self.candidate_count - len(self.selected),
                          "navigation_only": True},
            "max_participants_per_assessment": self.config.max_participants_per_assessment,
            "hypothesis_scopes": {key: sorted(value) for key, value in self.hypothesis_scopes.items()},
            "scope_issues": self.scope_issues,
        }
        navigation = []
        reads = []
        references = self.references()
        for candidate in self.selected:
            if state["plan"] is not None and candidate.component_id not in self.planned_ids:
                continue
            declaration = self.component(candidate.component_id)
            for identifier in candidate.relationship_ids[:4]:
                relationship = self.relationships[identifier]
                if relationship.resolution != "internal":
                    continue
                source, target = self.component(relationship.source_id), self.component(relationship.target_id)
                if not source or not target or source.file_id == target.file_id:
                    continue
                navigation.append({"declaration_id": candidate.component_id,
                    "relationship_id": identifier, "source_id": source.id, "target_id": target.id,
                    "source_path": source.path, "target_path": target.path, "kind": relationship.kind,
                    "navigation_only": True})
                for component in (declaration, source, target):
                    symbol = self.symbols.get(component.id)
                    file = self.files[component.file_id]
                    start = symbol.start_line if symbol else 1
                    end = min(symbol.end_line if symbol else file.line_count,
                              start + self.tools.limits.max_source_lines - 1)
                    if not end or any(r.kind == "source" and r.file_id == file.id
                                      and r.start_line <= start and r.end_line >= end for r in references):
                        continue
                    read = {"tool": "get_source_excerpt", "arguments": {
                        "path": file.path, "start_line": start, "end_line": end}}
                    if read not in reads:
                        reads.append(read)
        context["abstraction_navigation"] = navigation[:24]
        context["next_source_reads"] = reads[:6]
        if state["evaluation"]:
            context["assessment_validation"] = [{"id": a.id, "validation_issues": a.validation_issues,
                "participants": [{"component_id": p.component_id, "validation_issues": p.validation_issues}
                                 for p in a.participants]} for a in self.normalized_assessments(
                state["evaluation"], {h.id for h in state["hypotheses"]})]
        return context

    def structured_schema(self, schema):
        # Reuse the existing native-schema complexity mitigation, retaining full
        # local validation and the shared include_raw usage-accounting contract.
        return lean_schema(schema) if isinstance(self.model, BaseChatModel) else schema

    def component(self, identifier):
        symbol = self.symbols.get(identifier)
        source = self.files.get(symbol.file_id if symbol else identifier)
        return ComponentReference(id=identifier, file_id=source.id, path=source.path,
            symbol_name=symbol.qualified_name if symbol else None) if source else None

    def own_source(self, reference, component, *, declaration=False):
        if component is None or reference.kind != "source" or reference.file_id != component.file_id:
            return False
        symbol = self.symbols.get(component.id)
        if symbol is None:
            return True
        if declaration:
            return reference.start_line <= symbol.start_line <= reference.end_line
        return reference.start_line <= symbol.end_line and reference.end_line >= symbol.start_line

    def body_inspected(self, records, component, *, complete=False):
        if component is None:
            return False
        symbols = ([self.symbols[component.id]] if component.id in self.symbols else
                   [s for s in self.symbols.values() if s.file_id == component.file_id and s.parent_symbol_id is None])
        own = [r for r in records if r.kind == "source" and r.file_id == component.file_id]
        if complete and component.id in self.symbols:
            symbol = self.symbols[component.id]
            cursor = symbol.start_line
            for record in sorted(own, key=lambda r: r.start_line):
                if record.start_line > cursor:
                    break
                cursor = max(cursor, record.end_line + 1)
            return cursor > symbol.end_line
        return any(r.end_line > r.start_line and r.end_line > s.start_line
                   and r.start_line <= s.end_line for r in own for s in symbols)

    def resolve(self, identifiers, references):
        records = [references[i] for i in dict.fromkeys(identifiers) if i in references]
        records, mismatch = self.verify_references(records)
        issues = ["unknown_evidence_ids"] if set(identifiers) - references.keys() else []
        if mismatch:
            issues.append("commit_mismatch")
        return records, issues

    def normalize(self, assessment, hypotheses, references):
        declaration = self.component(assessment.declaration_id)
        ids = [*assessment.supporting_evidence_ids, *assessment.counterevidence_ids,
               *[i for p in assessment.participants for i in p.evidence_ids]]
        evidence, issues = self.resolve(ids, references)
        supporting = [r for r in evidence if r.id in assessment.supporting_evidence_ids]
        if declaration is None or assessment.declaration_id not in self.selected_ids:
            issues.append("declaration_not_a_selected_scoped_candidate")
        if assessment.hypothesis_id not in hypotheses:
            issues.append("unknown_hypothesis")
        if assessment.declaration_id not in self.hypothesis_scopes.get(assessment.hypothesis_id, set()):
            issues.append("declaration_outside_hypothesis_scope")
        if not assessment.counterevidence_analysis.strip() or not all(f.strip() for f in assessment.observed_facts):
            issues.append("observed_facts_and_counterevidence_analysis_required")
        if not any(self.own_source(r, declaration, declaration=True) for r in supporting):
            issues.append("abstraction_declaration_not_inspected")
        if not self.body_inspected(supporting, declaration, complete=True):
            issues.append("abstraction_body_not_inspected")
        if assessment.id in self.duplicate_assessments:
            issues.append("duplicate_assessment_id")
        if len(assessment.participants) > self.config.max_participants_per_assessment:
            issues.append("participant_count_limit")
        participants = []
        seen = set()
        for participant in assessment.participants[:self.config.max_participants_per_assessment]:
            component = self.component(participant.component_id)
            if component is None:
                issues.append("unknown_participant_component")
                continue
            records, errors = self.resolve(participant.evidence_ids, references)
            if participant.component_id == assessment.declaration_id:
                errors.append("participant_cannot_be_its_own_abstraction")
            identity = (participant.component_id, participant.role)
            if identity in seen:
                errors.append("duplicate_participant")
            seen.add(identity)
            if not any(self.own_source(r, component) for r in records):
                errors.append("participant_behavior_not_inspected")
            if participant.role in {"consumer", "implementation", "delegate", "composition", "test", "duplicate"} and not self.body_inspected(records, component):
                errors.append("participant_body_not_inspected")
            if participant.role != "duplicate":
                relationship = self.relationships.get(participant.relationship_id)
                primary = {declaration.id, declaration.file_id} if declaration else set()
                related = {component.id, component.file_id}
                source, target = (primary, related) if participant.role in {"delegate", "contract"} else (related, primary)
                if (relationship is None or relationship.resolution != "internal" or relationship.kind == "contains"
                        or relationship.source_id not in source or relationship.target_id not in target):
                    errors.append("usage_relationship_unverified")
                else:
                    anchors = [self.anchors[i] for i in relationship.evidence_ids if i in self.anchors]
                    if not any(r.kind == "source" and r.file_id == a.file_id and a.start_line is not None
                               and r.start_line <= a.start_line and r.end_line >= (a.end_line or a.start_line)
                               for r in evidence for a in anchors):
                        errors.append("usage_declaration_not_inspected")
            if errors:
                issues.append("participant_usage_not_verified")
            participants.append(InspectedParticipant(**participant.model_dump(exclude={"evidence_ids"}),
                evidence_ids=[r.id for r in records], component=component, evidence=records,
                validation_issues=errors))
        roles = {p.role for p in participants if not p.validation_issues}
        conclusion = assessment.conclusion
        if conclusion in {"useful_abstraction", "unnecessary_abstraction", "coupling", "justified_boundary"} and "consumer" not in roles:
            issues.append("actual_consumer_required")
        if conclusion == "useful_abstraction" and not (assessment.reuse_benefit.strip() and assessment.variation_points.strip()):
            issues.append("reuse_benefit_and_variation_analysis_required")
        if conclusion == "unnecessary_abstraction" and not (
                roles & {"delegate", "implementation"} and assessment.indirection_cost.strip()
                and assessment.proportional_alternative.strip()):
            issues.append("concrete_indirection_cost_and_alternative_required")
        if conclusion == "coupling" and not assessment.coupling_consequence.strip():
            issues.append("concrete_coupling_consequence_required")
        if conclusion == "missed_reuse" and not (
                "duplicate" in roles and assessment.duplication_comparison.strip()
                and assessment.variation_points.strip() and assessment.reuse_benefit.strip()):
            issues.append("inspected_duplication_and_reuse_tradeoff_required")
        if conclusion == "justified_boundary" and not (
                roles & {"implementation", "contract"} and assessment.boundary_justification.strip()):
            issues.append("inspected_boundary_justification_required")
        return InvestigatedAbstraction(
            **assessment.model_dump(exclude={"participants", "supporting_evidence_ids", "counterevidence_ids", "conclusion", "uncertainty"}),
            declaration=declaration, participants=participants, evidence=evidence,
            supporting_evidence_ids=[r.id for r in supporting],
            counterevidence_ids=[r.id for r in evidence if r.id in assessment.counterevidence_ids],
            conclusion="inconclusive" if issues else conclusion,
            uncertainty="high" if issues else assessment.uncertainty,
            validation_status="insufficient_evidence" if issues else "source_backed",
            validation_issues=list(dict.fromkeys(issues)),
        )

    def normalized_assessments(self, evaluation, hypotheses):
        references = {r.id: r for r in self.references()}
        return [self.normalize(a, hypotheses, references) for a in evaluation.abstraction_assessments[:self.config.max_candidates]]

    def finding_support(self, finding, by_id):
        linked = [by_id[i] for i in finding.assessment_ids if i in by_id]
        required = {r.id for a in linked for r in a.evidence}
        components = [c for a in linked for c in [a.declaration, *[p.component for p in a.participants]] if c is not None]
        allowed = {s for c in components for s in (c.id, c.path, c.symbol_name) if s}
        invalid = (finding.basis != "usage_evidence" or not linked or len(linked) != len(set(finding.assessment_ids))
            or len(set(finding.assessment_ids)) != len(finding.assessment_ids)
            or any(a.validation_status != "source_backed" or a.conclusion != finding.category for a in linked)
            or not required <= set(finding.evidence_ids) or not set(finding.components) <= allowed
            or not set(finding.evidence_ids) <= {r.id for r in self.references()}
            or finding.category == "useful_abstraction" and finding.kind != "design_observation")
        return linked, invalid

    async def evaluate_evidence(self, state):
        closing_stop = self.stop if self._closing_budget_reserved and self.stop == "token_limit" else ""
        if closing_stop:
            self.stop = ""
        try:
            update = await super().evaluate_evidence(state)
        finally:
            if closing_stop:
                self.stop = closing_stop
        current = update["evaluation"]
        if current is None:
            return update
        counts = Counter(a.id for a in current.abstraction_assessments)
        self.duplicate_assessments.difference_update(counts)
        self.duplicate_assessments.update(i for i, count in counts.items() if count > 1)
        prior = state["evaluation"]
        if prior is not None:
            current = current.model_copy(update={"abstraction_assessments": retain_previous(
                current.abstraction_assessments, prior.abstraction_assessments,
            )})
        normalized = self.normalized_assessments(current, {h.id for h in update["hypotheses"]})
        gaps = list(current.missing_information)
        hypotheses = []
        originals = {h.id: h for h in state["plan"].hypotheses} if state["plan"] else {}
        for hypothesis in update["hypotheses"]:
            proposed = hypothesis
            original = originals.get(hypothesis.id)
            if original:
                hypothesis = hypothesis.model_copy(update={"question": original.question,
                    "criterion_id": original.criterion_id, "evidence_needed": original.evidence_needed})
            scope = self.hypothesis_scopes.get(hypothesis.id, set())
            linked = [a for a in normalized if a.hypothesis_id == hypothesis.id and a.declaration_id in scope]
            if hypothesis.status in {"confirmed", "discarded"} and (not linked or any(
                    a.validation_status != "source_backed" or a.conclusion == "inconclusive" for a in linked)
                    or {a.declaration_id for a in linked} != scope or hypothesis.id in self.scope_issues):
                hypothesis = hypothesis.model_copy(update={"status": "inconclusive", "rationale":
                    f"Unverified model interpretation: {hypothesis.rationale}\nHost validation: linked abstraction assessments are missing or inconclusive."})
            hypotheses.append(hypothesis)
            self.hypothesis_validation_history.append(AbstractionHypothesisValidation(
                iteration=update["iterations"], proposed=proposed, validated=hypothesis))
        update["hypotheses"] = hypotheses
        current = current.model_copy(update={"hypotheses": hypotheses})
        gaps.extend("Resolve hypothesis " + h.id + " with evidence or an explicit uncertainty blocker."
                    for h in update["hypotheses"] if h.status in {"pending", "inconclusive"})
        for assessment in normalized:
            if assessment.declaration_id in self.hypothesis_scopes.get(assessment.hypothesis_id, set()) and (
                    assessment.validation_issues or assessment.conclusion == "inconclusive"):
                gaps.append(f"Resolve abstraction {assessment.id}: " + ", ".join(assessment.validation_issues or ["conclusion remains inconclusive"]))
        by_id = {a.id: a for a in normalized}
        for candidate in current.candidates:
            if self.finding_support(candidate, by_id)[1]:
                gaps.append(f"Resolve inspected usage, category and citation support for candidate {candidate.id}; names/counts/structure alone are not proof.")
        assessed = {a.declaration_id for a in normalized if a.validation_status == "source_backed" and a.conclusion != "inconclusive"}
        gaps.extend(f"Hypothesis {identifier}: {issue}" for identifier, issue in self.scope_issues.items())
        pending = sorted(self.planned_ids - assessed)
        if pending:
            gaps.append("Inspect planned abstraction declarations and actual usage, or report the evidence blocker: " + ", ".join(pending))
        if len(current.abstraction_assessments) > self.config.max_candidates:
            gaps.append("Assessment count exceeds the configured candidate budget.")
        update["evaluation"] = current.model_copy(update={"sufficient": current.sufficient and not gaps,
            "missing_information": list(dict.fromkeys(gaps))})
        update["missing_information"] = update["evaluation"].missing_information
        blocked = [a for a in normalized if a.declaration_id in self.hypothesis_scopes.get(a.hypothesis_id, set())
                   and (a.validation_issues or a.conclusion == "inconclusive")]
        if blocked:
            relevant_files = {c.file_id for a in blocked for c in
                              [a.declaration, *[p.component for p in a.participants]] if c}
            fingerprint = json.dumps({"issues": sorted((a.hypothesis_id, a.declaration_id,
                a.validation_issues, [(p.component_id, p.validation_issues) for p in a.participants]) for a in blocked),
                "coverage": sorted((r.file_id, r.start_line, r.end_line) for r in self.references()
                                   if r.kind == "source" and r.file_id in relevant_files)}, sort_keys=True)
            if fingerprint == self._last_blocked_progress and not self.stop:
                self.stop = "no_investigation_progress"
                self.issues.append("Abstraction repair made no relevant source/validation progress; stopped exploration to preserve critical review.")
            self._last_blocked_progress = fingerprint
        else:
            self._last_blocked_progress = None
        return update

    def is_sufficient(self, state):
        evaluation = state["evaluation"]
        if evaluation and not evaluation.sufficient and not evaluation.missing_information and not self.stop:
            self.final_reason = "no_actionable_gap"
            return "review_findings"
        return super().is_sufficient(state)

    async def review_findings(self, state):
        update = await super().review_findings(state)
        if self.final_reason and not self.stop:
            update["termination_reason"] = self.final_reason
        return update

    def finalize(self, state):
        result = super().finalize(state)["result"]
        evaluation = state["evaluation"]
        assessments = self.normalized_assessments(evaluation, {h.id for h in result.hypotheses}) if evaluation else []
        by_id = {a.id: a for a in assessments}
        missing = list(result.missing_information)
        review = state["review"]
        judgments = review.hypotheses if isinstance(review, AbstractionReview) else []
        references = {r.id: r for r in self.references()}
        hypotheses = []
        for hypothesis in result.hypotheses:
            if hypothesis.status != "pending":
                matches = [j for j in judgments if j.hypothesis_id == hypothesis.id]
                judgment = matches[0] if len(matches) == 1 else None
                linked = [by_id[i] for i in judgment.assessment_ids if i in by_id] if judgment else []
                required = set(hypothesis.evidence_ids)
                valid = (judgment and judgment.status == "supported" and judgment.scope_supported
                    and judgment.resolution in {"confirmed", "discarded"}
                    and not judgment.unverified_claims and required
                    and required <= set(judgment.checked_evidence_ids)
                    and set(judgment.checked_evidence_ids) <= references.keys()
                    and linked and len(linked) == len(set(judgment.assessment_ids))
                    and len(judgment.assessment_ids) == len(set(judgment.assessment_ids))
                    and all(a.hypothesis_id == hypothesis.id and a.validation_status == "source_backed"
                            and a.conclusion != "inconclusive" for a in linked)
                    and {a.declaration_id for a in linked} == self.hypothesis_scopes.get(hypothesis.id, set())
                    and hypothesis.id not in self.scope_issues
                    and required <= {r.id for a in linked for r in a.evidence}
                    and {r.id for a in linked for r in a.evidence} <= set(judgment.checked_evidence_ids)
                    and not self.evidence_issues(list(required), references)[1])
                if not valid:
                    reason = "Abstraction hypothesis scope was not independently verified against valid linked assessments."
                    hypothesis = hypothesis.model_copy(update={"status": "inconclusive", "rationale":
                        f"Unverified model interpretation: {hypothesis.rationale}\nHost validation: {reason}"})
                    missing.append(f"Hypothesis {hypothesis.id}: {reason}")
                else:
                    hypothesis = hypothesis.model_copy(update={"status": judgment.resolution,
                        "rationale": judgment.rationale})
                    # Remove only the runtime's hypothesis-resolution tasks. Source,
                    # provider and model-declared gaps remain independent limitations.
                    prefixes = (f"Resolve hypothesis {hypothesis.id} with evidence or an explicit uncertainty blocker.",
                        f"Resolve hypothesis {hypothesis.id} with source evidence or explain its concrete blocker:")
                    missing = [gap for gap in missing if not gap.startswith(prefixes)]
            hypotheses.append(hypothesis)
        result = result.model_copy(update={"hypotheses": hypotheses})
        findings = []
        accepted_keys = {}
        for finding in result.findings:
            linked, invalid = self.finding_support(finding, by_id)
            resolved = {h.id for h in hypotheses if h.status in {"confirmed", "discarded"}}
            unresolved = sorted({a.hypothesis_id for a in linked if a.hypothesis_id not in resolved})
            reason = ("Abstraction host validation failed: require scoped declarations, inspected usage/consumers, concrete tradeoffs and complete source citations; names, counts and interfaces alone are not proof."
                if invalid else "Abstraction hypothesis scope review is unavailable, incomplete or unsupported: " + ", ".join(unresolved))
            invalid |= bool(unresolved)
            if invalid and finding.validation_status != "rejected":
                finding = finding.model_copy(update={"validation_status": "insufficient_evidence", "confidence": 0,
                    "review_rationale": reason})
            if finding.category == "useful_abstraction":
                finding = finding.model_copy(update={"severity": "info"})
            key = (finding.category, tuple(sorted(a.declaration_id for a in linked)), " ".join(finding.title.casefold().split()))
            if finding.validation_status == "accepted":
                if key in accepted_keys:
                    index = accepted_keys[key]
                    first = findings[index]
                    findings[index] = first.model_copy(update={
                        "evidence": list({r.id: r for r in [*first.evidence, *finding.evidence]}.values()),
                        "evidence_ids": list(dict.fromkeys([*first.evidence_ids, *finding.evidence_ids])),
                        "assessment_ids": list(dict.fromkeys([*first.assessment_ids, *finding.assessment_ids])),
                        "confidence": min(first.confidence, finding.confidence),
                    })
                    finding = finding.model_copy(update={"duplicate_of": first.id, "validation_status": "rejected", "confidence": 0,
                        "review_rationale": "Duplicate concern consolidated into " + first.id + "; original candidate retained for traceability."})
                else:
                    accepted_keys[key] = len(findings)
            findings.append(finding)
        inconclusive = [a.id for a in assessments if a.conclusion == "inconclusive"]
        inconclusive.extend(h.id for h in result.hypotheses if h.status in {"pending", "inconclusive"})
        assessed = {a.declaration_id for a in assessments if a.validation_status == "source_backed" and a.conclusion != "inconclusive"}
        unassessed = sorted(self.planned_ids - assessed)
        scoped_inconclusive = [a.id for a in assessments if a.conclusion == "inconclusive"
            and a.declaration_id in self.hypothesis_scopes.get(a.hypothesis_id, set())]
        complete = (state["termination_reason"] == "sufficient_evidence" and result.plan is not None and state["review"] is not None
                    and not missing and not scoped_inconclusive and not unassessed
                    and not self.scope_issues and not any(h.status in {"pending", "inconclusive"} for h in hypotheses)
                    and not any(f.validation_status == "insufficient_evidence" for f in findings))
        status = "completed" if complete else "failed" if result.plan is None and not self.references() else "partial"
        limitations = [*result.limitations,
            "Candidate ranking uses static indexes, not a quality score; source and relationship validation does not prove semantic reuse benefits or runtime behavior.",
            "Only resolved internal usage relationships can be structurally verified; external, dynamic and missing relationships remain inconclusive.",
            "Discovery is selective and bounded; unselected declarations and wider repository reuse are not certified."]
        limitations.append("Coverage inspected_paths records files with retrieved fragments, including search hits; it does not certify complete file inspection.")
        if any("declaration_outside_hypothesis_scope" in a.validation_issues for a in assessments):
            limitations.append("Assessments outside their hypothesis's planned declaration scope are retained as inconclusive; they do not support or invalidate an unrelated scoped conclusion.")
        if not any(h.status in {"pending", "inconclusive"} for h in hypotheses):
            limitations = [item for item in limitations if item != "Some hypotheses remain inconclusive; absence of findings does not establish boundary compliance."]
        limitations = [s.replace("absence of findings does not establish boundary compliance", "absence of findings does not establish abstraction quality") for s in limitations]
        return {"result": AbstractionResult.model_validate({**result.model_dump(), "findings": findings, "status": status,
            "critical_review": review, "missing_information": list(dict.fromkeys(missing)),
            "hypothesis_validation_history": self.hypothesis_validation_history,
            "termination_reason": "sufficient_evidence" if complete else
                "evidence_validation_failed" if result.termination_reason == "sufficient_evidence" else result.termination_reason,
            "abstractions_investigated": assessments, "inconclusive_investigations": list(dict.fromkeys(inconclusive + unassessed)),
            "tool_failures": [f"{m.tool}:{m.call_id}:{m.status}" for m in self.tools.tool_measurements if m.status != "ok"],
            "limitations": limitations, "coverage": AbstractionCoverage(targets=self.request.targets,
                selected_candidates=self.selected, candidate_count=self.candidate_count,
                omitted_candidates=self.candidate_count - len(self.selected),
                inspected_paths=sorted({r.path for r in self.references() if r.kind == "source"}),
                assessed_declarations=sorted(assessed), planned_declarations=sorted(self.planned_ids),
                unplanned_candidates=sorted(self.selected_ids - self.planned_ids),
                unassessed_candidates=unassessed).model_dump()})}


