"""Analysability policy over the shared five-node graph and read-only tool ledger."""

import json
from collections import Counter
from pathlib import Path

from server.runtimes.investigation.agent import InvestigationExecution
from server.runtimes.investigation.messages import compact_tool_history
from server.runtimes.investigation.records import retain_previous

from .representations import project_navigation
from .schemas import (
    CandidateDiagnostic,
    CodeComprehensionEvaluation,
    CodeComprehensionFinding,
    CodeComprehensionPlan,
    CodeComprehensionResult,
    CodeComprehensionReview,
    InvestigatedComprehension,
)


class CodeComprehensionExecution(InvestigationExecution):
    trace_name = "code-comprehension"
    tool_prefix = "code-comprehension"
    prompt_directory = Path(__file__).parent / "prompts"
    plan_schema = CodeComprehensionPlan
    evaluation_schema = CodeComprehensionEvaluation
    finding_schema = CodeComprehensionFinding
    review_schema = CodeComprehensionReview
    result_schema = CodeComprehensionResult

    def __init__(self, model, config, tools, request):
        super().__init__(model, config, tools, request)
        snapshot = tools.accessible_snapshot
        self.files = {f.id: f for f in snapshot.files}
        self.symbols = {s.id: s for s in snapshot.symbols}
        self.paths = {f.path: f.id for f in snapshot.files}
        self.navigation, representation_issues = project_navigation(request.representations, snapshot.repository.snapshot_hash)
        self.issues.extend(representation_issues)
        targets = [*request.targets, *[i for c in request.follow_up for i in (*c.subject_ids, *c.paths)]]
        if not targets:
            orientation = self.navigation.get("orientation", {})
            architecture = self.navigation.get("architecture", {})
            targets = [*[p["file_id"] for p in orientation.get("starting_points", [])],
                *[i for c in architecture.get("organization", []) for i in c["file_ids"]],
                *[e.symbol_id or e.file_id for e in snapshot.entrypoints if e.symbol_id or e.file_id],
                *[f.id for f in snapshot.files]]
        selected = []
        for target in targets:
            identifier = self.resolve(target)
            if identifier and identifier not in selected:
                selected.append(identifier)
            elif not identifier and (request.targets or request.follow_up):
                self.issues.append(f"Unresolved requested component: {target}")
        self.selected = selected[:config.max_components]
        if len(selected) > len(self.selected):
            self.issues.append(f"Component limit omitted {len(selected) - len(self.selected)} navigation targets; conclusions cover selected components only.")
        self.hypothesis_scopes = {}
        self._progress = None

    def resolve(self, identifier):
        return identifier if identifier in self.files or identifier in self.symbols else self.paths.get(identifier)

    def component(self, identifier):
        symbol = self.symbols.get(identifier)
        source = self.files.get(symbol.file_id if symbol else identifier)
        return source, symbol

    async def plan_investigation(self, state):
        update = await super().plan_investigation(state)
        plan = update["plan"]
        if plan is None:
            return update
        hypotheses, invalid = [], not plan.hypotheses
        for hypothesis in plan.hypotheses:
            ids = list(dict.fromkeys(self.resolve(i) or i for i in hypothesis.component_ids))
            if not set(ids) <= set(self.selected):
                invalid = True
            self.hypothesis_scopes[hypothesis.id] = set(ids)
            hypotheses.append(hypothesis.model_copy(update={"component_ids": ids}))
        if invalid:
            self.stop = "invalid_plan"
            self.issues.append("Plan requires nonempty hypotheses scoped to the supplied accessible component IDs.")
            return {**update, "plan": None, "hypotheses": [], "termination_reason": self.stop,
                "missing_information": ["Produce a plan scoped to accessible selected components."]}
        return {**update, "plan": plan.model_copy(update={"hypotheses": hypotheses}), "hypotheses": hypotheses}

    def _context(self, state):
        context = super()._context(state)
        context.update(quality_attribute="maintainability", subcharacteristic="analysability",
            project_representations=self.navigation, hypothesis_scopes={k: sorted(v) for k, v in self.hypothesis_scopes.items()},
            selected_components=[{"id": i, "path": self.component(i)[0].path,
                "symbol": self.component(i)[1].qualified_name if self.component(i)[1] else None} for i in self.selected],
            max_related_components_per_assessment=self.config.max_related_components_per_assessment)
        reads = []
        references = self.references()
        ids = set().union(*self.hypothesis_scopes.values()) if self.hypothesis_scopes else set(self.selected)
        for identifier in self.selected:
            if identifier not in ids:
                continue
            source, symbol = self.component(identifier)
            start = symbol.start_line if symbol else 1
            end = symbol.end_line if symbol else source.line_count or 0
            # Union delivered intervals: adjacent excerpts together satisfy a range.
            for record in sorted((r for r in references if r.kind == "source" and r.file_id == source.id),
                    key=lambda r: r.start_line):
                if record.end_line < start:
                    continue
                if record.start_line > start:
                    end = min(end, record.start_line - 1)
                    break
                start = max(start, record.end_line + 1)
            end = min(end, start + self.tools.limits.max_source_lines - 1)
            if end >= start:
                reads.append({"tool": "get_source_excerpt", "arguments": {
                    "path": source.path, "start_line": start, "end_line": end}})
        context["next_source_reads"] = reads[:6]
        return context

    def model_context(self, node, state):
        context = self._context(state)
        context["evidence"] = [{k: v for k, v in r.items() if k in {
            "id", "file_id", "path", "kind", "start_line", "end_line", "symbol_ids"}} for r in context["evidence"]]
        for key in ("plan", "evaluation"):
            if context[key]:
                context[key] = {k: v for k, v in context[key].items() if k != "hypotheses"}
        if node != "plan_investigation":
            context.pop("project_representations", None)
        if node != "investigate":
            context.pop("inventory", None)
        return context

    def provider_history(self, state, messages, *, overhead_characters=0, node=None):
        pinned = {i for h in state["hypotheses"] for i in h.evidence_ids}
        evaluation = state["evaluation"]
        if evaluation:
            pinned.update(i for c in evaluation.candidates for i in c.evidence_ids)
            for assessment in evaluation.comprehension_assessments:
                pinned.update(self.assessment_ids(assessment))
        used = len(json.dumps([m.model_dump() for m in messages], default=str)) + overhead_characters
        return compact_tool_history(state["messages"], max(0, self.config.max_context_characters - used), pinned,
            compact_metadata=True)

    def prepare_structured_result(self, node, result, state):
        if node == "evaluate_evidence" and state["evaluation"]:
            return result.model_copy(update={"comprehension_assessments": retain_previous(
                result.comprehension_assessments, state["evaluation"].comprehension_assessments)})
        return result

    def validate_evaluation(self, evaluation, state):
        super().validate_evaluation(evaluation, state)
        for hypothesis in evaluation.hypotheses:
            resolved = {self.resolve(i) for i in hypothesis.component_ids}
            if resolved != self.hypothesis_scopes.get(hypothesis.id):
                raise ValueError("Hypothesis component_ids must preserve the original planned scope.")

    @staticmethod
    def assessment_ids(assessment):
        return list(dict.fromkeys([*assessment.supporting_evidence_ids, *assessment.counterevidence_ids,
            *[i for p in assessment.participants for i in p.evidence_ids]]))

    def own_body(self, records, identifier):
        source, symbol = self.component(identifier)
        if source is None:
            return False
        symbols = [symbol] if symbol else [s for s in self.symbols.values() if s.file_id == source.id]
        return any(r.kind == "source" and r.file_id == source.id and r.end_line > r.start_line
            and (not symbols or any(r.end_line > s.start_line and r.start_line <= s.end_line for s in symbols))
            for r in records)

    def normalize(self, assessment, references, duplicates):
        identifier = self.resolve(assessment.component_id) or assessment.component_id
        source, symbol = self.component(identifier)
        evidence, issues = self.evidence_issues(self.assessment_ids(assessment), references)
        if identifier not in self.hypothesis_scopes.get(assessment.hypothesis_id, set()):
            issues.append("component_outside_planned_hypothesis")
        if assessment.id in duplicates:
            issues.append("duplicate_assessment_id")
        supporting = [references[i] for i in assessment.supporting_evidence_ids if i in references]
        if not self.own_body(supporting, identifier):
            issues.append("component_body_not_inspected")
        if assessment.basis != "behavioral":
            issues.append("behavioral_support_required")
        if not all(v.strip() for v in (assessment.responsibility, assessment.observed_behavior,
                assessment.comprehension_question, assessment.alternative_explanation, assessment.counterevidence_analysis)):
            issues.append("concrete_behavior_and_counterevidence_required")
        if assessment.conclusion == "problematic" and not all(v.strip() for v in (
                assessment.difficulty, assessment.comprehension_impact)):
            issues.append("comprehension_difficulty_and_impact_required")
        if len(assessment.participants) > self.config.max_related_components_per_assessment:
            issues.append("related_component_limit")
        participant_ids = [self.resolve(p.component_id) for p in assessment.participants]
        if len(participant_ids) != len(set(participant_ids)):
            issues.append("duplicate_participant")
        for participant in assessment.participants:
            records = [references[i] for i in participant.evidence_ids if i in references]
            if not self.own_body(records, self.resolve(participant.component_id)):
                issues.append("participant_body_not_inspected")
        if assessment.conclusion == "inconclusive":
            issues.append("assessment_inconclusive")
        # Sanitize all nested citations, including inconclusive work.
        value = assessment.model_dump()
        value.update(component_id=identifier,
            supporting_evidence_ids=[i for i in assessment.supporting_evidence_ids if i in references],
            counterevidence_ids=[i for i in assessment.counterevidence_ids if i in references],
            participants=[p.model_copy(update={"evidence_ids": [i for i in p.evidence_ids if i in references]}).model_dump()
                for p in assessment.participants])
        return InvestigatedComprehension(**value, path=source.path if source else None,
            file_id=source.id if source else None, symbol_name=symbol.qualified_name if symbol else None,
            evidence=evidence, validation_status="insufficient_evidence" if issues else "source_backed",
            validation_issues=list(dict.fromkeys(issues)))

    def assessments(self, evaluation):
        references = {r.id: r for r in self.references()}
        counts = Counter(a.id for a in evaluation.comprehension_assessments)
        duplicates = {i for i, count in counts.items() if count > 1}
        return [self.normalize(a, references, duplicates) for a in evaluation.comprehension_assessments]

    def candidate_issues(self, candidate, assessments):
        linked = [a for a in assessments if a.id in candidate.assessment_ids]
        issues = []
        criterion = next((c for c in self.request.criteria if c.id == candidate.criterion_id), None)
        if criterion is None:
            issues.append("unknown_criterion")
        elif candidate.kind == "violation" and criterion.origin != "explicit":
            issues.append("violation_requires_explicit_criterion")
        if len(set(candidate.assessment_ids)) != len(candidate.assessment_ids) or len(linked) != len(candidate.assessment_ids):
            issues.append("unknown_or_duplicate_assessment")
        if any(a.validation_status != "source_backed" or a.conclusion != "problematic" for a in linked):
            issues.append("problematic_source_backed_assessment_required")
        if not {i for a in linked for i in self.assessment_ids(a)} <= set(candidate.evidence_ids):
            issues.append("assessment_citations_missing_from_finding")
        components = {self.resolve(i) for i in candidate.components}
        primary = {a.component_id for a in linked}
        allowed = primary | {self.resolve(p.component_id) for a in linked for p in a.participants}
        if None in components or not primary <= components <= allowed:
            issues.append("finding_component_scope_mismatch")
        return issues

    def evaluation_evidence_gaps(self, evaluation):
        gaps = super().evaluation_evidence_gaps(evaluation)
        assessments = self.assessments(evaluation)
        # Preserve the shared distinction between repairable source gaps and immutable provenance blockers.
        provenance_codes = {check.reason for check in self._commit_checks.values() if not check.matched}
        preflight = [a.model_copy(update={"validation_status": "source_backed"})
            if a.validation_issues and set(a.validation_issues) <= provenance_codes else a for a in assessments]
        domain_gaps = []
        for assessment in assessments:
            issues = set(assessment.validation_issues) - provenance_codes
            if issues:
                domain_gaps.append(f"Assessment {assessment.id}: {', '.join(sorted(issues))}. Inspect the relevant body/participants or correct the scoped claim.")
        for candidate in evaluation.candidates:
            issues = self.candidate_issues(candidate, preflight)
            if issues:
                domain_gaps.append(f"Candidate {candidate.id}: {', '.join(issues)}.")
        for hypothesis in evaluation.hypotheses:
            scoped = [a for a in preflight if a.hypothesis_id == hypothesis.id]
            if hypothesis.status in {"confirmed", "discarded"} and (
                    not hypothesis.evidence_ids or not scoped
                    or {a.component_id for a in scoped if a.validation_status == "source_backed"}
                        != self.hypothesis_scopes.get(hypothesis.id, set())
                    or any(a.conclusion != ("problematic" if hypothesis.status == "confirmed" else "clear") for a in scoped)):
                domain_gaps.append(f"Hypothesis {hypothesis.id}: require scoped behavioral assessments and delivered source citations.")
        if domain_gaps:
            self.provenance_blocked = False
        return list(dict.fromkeys([*gaps, *domain_gaps]))

    async def evaluate_evidence(self, state):
        update = await super().evaluate_evidence(state)
        evaluation = update["evaluation"]
        if evaluation:
            # Repeated delivery creates fresh citation IDs, not new knowledge.
            # Compare source identities and canonicalized citations rather than
            # rewarding another read of identical immutable bytes.
            identities = {r.id: json.dumps((r.file_id, r.content_hash, r.kind, r.start_line, r.end_line))
                for r in self.references()}

            def canonical(value):
                if isinstance(value, str):
                    return identities.get(value, value)
                if isinstance(value, list):
                    return [canonical(item) for item in value]
                if isinstance(value, dict):
                    return {key: sorted({canonical(item) for item in items}) if key.endswith("evidence_ids")
                        else canonical(items) for key, items in value.items()}
                return value

            progress = (tuple(sorted(set(identities.values()))), json.dumps(canonical(evaluation.model_dump()), sort_keys=True))
            if not evaluation.sufficient and progress == self._progress:
                self.stop = "no_investigation_progress"
                self.issues.append("Repeated evaluation without new evidence or changed conclusions; stop redundant investigation.")
            self._progress = progress
        return update

    def finalize(self, state):
        # Shared finalization performs evidence/criterion/provenance validation without a model call.
        result = super().finalize(state)["result"]
        evaluation, review = state["evaluation"], state["review"]
        assessments = self.assessments(evaluation) if evaluation else []
        references = {r.id: r for r in result.evidence}
        accepted, diagnostics = [], []
        for finding in result.findings:
            issues = self.candidate_issues(finding, assessments)
            judgment = next((j for j in review.findings if j.finding_id == finding.id), None) if review else None
            if judgment is None or not judgment.scope_supported or judgment.unverified_claims or not (
                    set(finding.evidence_ids) <= set(judgment.checked_evidence_ids) <= references.keys()):
                issues.append("independent_scope_review_required")
            if finding.validation_status == "accepted" and not issues:
                accepted.append(finding)
            else:
                diagnostics.append(CandidateDiagnostic(candidate_id=finding.id,
                    status="rejected" if finding.validation_status == "rejected" else "insufficient_evidence",
                    reasons=list(dict.fromkeys([*issues, finding.review_rationale]))))
        # The neutral finalizer omits candidates with unknown criteria; retain their
        # diagnostics and do not let that omission turn into a successful closure.
        finalized = {f.id for f in result.findings}
        for candidate in evaluation.candidates if evaluation else []:
            if candidate.id not in finalized:
                diagnostics.append(CandidateDiagnostic(candidate_id=candidate.id, status="insufficient_evidence",
                    reasons=self.candidate_issues(candidate, assessments) or ["candidate_failed_common_validation"]))
        missing = list(result.missing_information)
        hypotheses = []
        for hypothesis in result.hypotheses:
            if hypothesis.status in {"confirmed", "discarded"}:
                judgments = [j for j in review.hypotheses if j.hypothesis_id == hypothesis.id] if review else []
                judgment = judgments[0] if len(judgments) == 1 else None
                linked = [a for a in assessments if judgment and a.id in judgment.assessment_ids]
                expected = "problematic" if hypothesis.status == "confirmed" else "clear"
                valid = (judgment and judgment.status == "supported" and judgment.scope_supported
                    and not judgment.unverified_claims and hypothesis.evidence_ids
                    and set(hypothesis.evidence_ids) <= set(judgment.checked_evidence_ids) <= references.keys()
                    and linked and len(linked) == len(set(judgment.assessment_ids))
                    and all(a.hypothesis_id == hypothesis.id and a.validation_status == "source_backed"
                        and a.conclusion == expected for a in linked)
                    and {a.component_id for a in linked} == self.hypothesis_scopes.get(hypothesis.id, set())
                    and set(hypothesis.evidence_ids) <= {i for a in linked for i in self.assessment_ids(a)})
                if not valid:
                    hypothesis = hypothesis.model_copy(update={"status": "inconclusive",
                        "rationale": hypothesis.rationale + "\nHost validation: scoped behavioral conclusion was not independently reviewed."})
                    missing.append(f"Hypothesis {hypothesis.id}: independently review all scoped components and their source citations.")
            hypotheses.append(hypothesis)
        missing.extend(f"Assessment {a.id}: {', '.join(a.validation_issues)}" for a in assessments if a.validation_issues)
        failed = missing or any(d.status == "insufficient_evidence" for d in diagnostics)
        reason = "evidence_validation_failed" if failed and result.termination_reason == "sufficient_evidence" else result.termination_reason
        return {"result": CodeComprehensionResult.model_validate({**result.model_dump(),
            "findings": accepted, "comprehension_assessments": assessments, "candidate_diagnostics": diagnostics,
            "hypotheses": hypotheses, "critical_review": review,
            "discarded_hypotheses": [h for h in hypotheses if h.status == "discarded"],
            "inconclusive_investigations": [h.id for h in hypotheses if h.status == "inconclusive"],
            "missing_information": list(dict.fromkeys(missing)), "termination_reason": reason})}
