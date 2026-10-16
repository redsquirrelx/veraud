"""Independent reusability investigator using the existing native LangGraph runtime."""

from collections import Counter
from pathlib import Path

from langchain_core.language_models.chat_models import BaseChatModel

from .....runtimes.investigation.agent import InvestigationExecution
from .....runtimes.investigation.provider import lean_schema
from .....runtimes.investigation.records import retain_previous
from .discovery import discover
from .schemas import (
    AbstractionCoverage,
    AbstractionEvaluation,
    AbstractionFinding,
    AbstractionResult,
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

    def _context(self, state):
        return super()._context(state) | {
            "quality_attribute": "reusability", "declaration_scope": self.request.targets,
            "abstraction_candidates": [c.model_dump() for c in self.selected],
            "discovery": {"candidate_count": self.candidate_count,
                          "omitted_candidates": self.candidate_count - len(self.selected),
                          "navigation_only": True},
            "max_participants_per_assessment": self.config.max_participants_per_assessment,
        }

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
        if not assessment.counterevidence_analysis.strip() or not all(f.strip() for f in assessment.observed_facts):
            issues.append("observed_facts_and_counterevidence_analysis_required")
        if not any(self.own_source(r, declaration, declaration=True) for r in supporting):
            issues.append("abstraction_declaration_not_inspected")
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
        update = await super().evaluate_evidence(state)
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
        gaps.extend("Resolve hypothesis " + h.id + " with evidence or an explicit uncertainty blocker."
                    for h in update["hypotheses"] if h.status in {"pending", "inconclusive"})
        for assessment in normalized:
            if assessment.validation_issues or assessment.conclusion == "inconclusive":
                gaps.append(f"Resolve abstraction {assessment.id}: " + ", ".join(assessment.validation_issues or ["conclusion remains inconclusive"]))
        by_id = {a.id: a for a in normalized}
        for candidate in current.candidates:
            if self.finding_support(candidate, by_id)[1]:
                gaps.append(f"Resolve inspected usage, category and citation support for candidate {candidate.id}; names/counts/structure alone are not proof.")
        assessed = {a.declaration_id for a in normalized if a.validation_status == "source_backed" and a.conclusion != "inconclusive"}
        pending = sorted(self.selected_ids - assessed)
        if pending:
            gaps.append("Inspect selected abstraction declarations and actual usage, or report the evidence blocker: " + ", ".join(pending))
        if len(current.abstraction_assessments) > self.config.max_candidates:
            gaps.append("Assessment count exceeds the configured candidate budget.")
        update["evaluation"] = current.model_copy(update={"sufficient": current.sufficient and not gaps,
            "missing_information": list(dict.fromkeys(gaps))})
        update["missing_information"] = update["evaluation"].missing_information
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
        findings = []
        accepted_keys = {}
        for finding in result.findings:
            linked, invalid = self.finding_support(finding, by_id)
            if invalid and finding.validation_status != "rejected":
                finding = finding.model_copy(update={"validation_status": "insufficient_evidence", "confidence": 0,
                    "review_rationale": "Abstraction host validation failed: require scoped declarations, inspected usage/consumers, concrete tradeoffs and complete source citations; names, counts and interfaces alone are not proof."})
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
        unassessed = sorted(self.selected_ids - assessed)
        complete = (result.termination_reason == "sufficient_evidence" and result.plan is not None and state["review"] is not None
                    and not result.missing_information and not inconclusive and not unassessed
                    and not any(f.validation_status == "insufficient_evidence" for f in findings))
        status = "completed" if complete else "failed" if result.plan is None and not self.references() else "partial"
        limitations = [*result.limitations,
            "Candidate ranking uses static indexes, not a quality score; source and relationship validation does not prove semantic reuse benefits or runtime behavior.",
            "Only resolved internal usage relationships can be structurally verified; external, dynamic and missing relationships remain inconclusive.",
            "Discovery is selective and bounded; unselected declarations and wider repository reuse are not certified."]
        limitations = [s.replace("absence of findings does not establish boundary compliance", "absence of findings does not establish abstraction quality") for s in limitations]
        return {"result": AbstractionResult.model_validate({**result.model_dump(), "findings": findings, "status": status,
            "abstractions_investigated": assessments, "inconclusive_investigations": list(dict.fromkeys(inconclusive + unassessed)),
            "tool_failures": [f"{m.tool}:{m.call_id}:{m.status}" for m in self.tools.tool_measurements if m.status != "ok"],
            "limitations": limitations, "coverage": AbstractionCoverage(targets=self.request.targets,
                selected_candidates=self.selected, candidate_count=self.candidate_count,
                omitted_candidates=self.candidate_count - len(self.selected),
                inspected_paths=sorted({r.path for r in self.references() if r.kind == "source"}),
                assessed_declarations=sorted(assessed), unassessed_candidates=unassessed).model_dump()})}


