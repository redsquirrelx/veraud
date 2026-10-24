"""Source-grounded dependency-impact specialization of the shared LangGraph cycle."""

import json
from itertools import pairwise
from pathlib import Path

from .....config.token_budget import token_budget_exceeded
from .....runtimes.investigation.agent import InvestigationExecution
from .....runtimes.investigation.messages import compact_tool_history
from .....runtimes.investigation.records import retain_previous
from .schemas import (
    ComponentReference,
    DependencyImpactEvaluation,
    DependencyImpactFinding,
    DependencyImpactResult,
    DependencyImpactReview,
    InvestigatedDependency,
    InvestigatedImpact,
)


class DependencyImpactExecution(InvestigationExecution):
    trace_name = "dependency-impact"
    tool_prefix = "dependency-impact"
    prompt_directory = Path(__file__).parent / "prompts"
    evaluation_schema = DependencyImpactEvaluation
    finding_schema = DependencyImpactFinding
    result_schema = DependencyImpactResult
    review_schema = DependencyImpactReview

    def __init__(self, model, config, tools, request):
        self._closing_budget_reserved = False
        self._last_blocked_progress = None
        super().__init__(model, config, tools, request)

    def closing_token_reserve(self, node, request_reserve):
        reserve = (min(self.token_limit // 3, 2 * request_reserve) if node == "investigate"
                   else min(self.token_limit // 6, request_reserve) if node == "evaluate_evidence" else 0)
        if reserve and token_budget_exceeded(self.tokens + request_reserve + reserve, self.token_limit):
            self._closing_budget_reserved = True
        return reserve

    def can_review_stopped(self, state):
        return super().can_review_stopped(state) or (
            state["evaluation"] is not None and self._closing_budget_reserved and self.stop == "token_limit")

    def model_context(self, node, state):
        context = self._context(state)
        context["evidence"] = [{key: value for key, value in item.items() if key in {
            "id", "file_id", "path", "kind", "start_line", "end_line", "symbol_ids"}}
            for item in context["evidence"]]
        if context["plan"]:
            context["plan"] = {key: value for key, value in context["plan"].items() if key != "hypotheses"}
        if context["evaluation"]:
            context["evaluation"] = {key: value for key, value in context["evaluation"].items() if key != "hypotheses"}
        if node != "investigate":
            context.pop("inventory", None)
            context.pop("dependency_navigation", None)
            context.pop("dependency_navigation_notice", None)
        context["closing_due_to_token_budget"] = self._closing_budget_reserved
        return context

    def provider_history(self, state, messages, *, overhead_characters=0, node=None):
        pinned = {i for h in state["hypotheses"] for i in h.evidence_ids}
        evaluation = state["evaluation"]
        if evaluation:
            pinned.update(i for c in evaluation.candidates for i in c.evidence_ids)
            for assessment in evaluation.dependency_assessments:
                pinned.update([*assessment.supporting_evidence_ids, *assessment.contradicting_evidence_ids,
                               *assessment.demonstration_evidence_ids])
                pinned.update(i for link in assessment.dependencies for i in link.evidence_ids)
        used = len(json.dumps([item.model_dump() for item in messages], default=str)) + overhead_characters
        allowance = max(0, int(self.config.max_context_characters * 0.4) - used)
        return compact_tool_history(state["messages"], allowance, pinned)

    def _context(self, state):
        context = super()._context(state) | {"dependency_limits": {
            "max_depth": self.config.max_dependency_depth,
            "max_relationships_per_assessment": self.config.max_relationships_per_assessment,
        }}
        snapshot = self.tools.accessible_snapshot
        files = {f.id: f for f in snapshot.files}
        symbols = {s.id: s for s in snapshot.symbols}
        anchors = {e.id: e for e in snapshot.evidence}
        scopes = state["plan"].components if state["plan"] else []
        relationships = []
        per_scope = {}
        for relationship in snapshot.relationships:
            if relationship.resolution != "internal" or relationship.kind == "contains":
                continue
            source_symbol = symbols.get(relationship.source_id)
            target_symbol = symbols.get(relationship.target_id)
            source = files.get(source_symbol.file_id if source_symbol else relationship.source_id)
            target = files.get(target_symbol.file_id if target_symbol else relationship.target_id)
            if not source or not target or source.id == target.id:
                continue
            matched_scope = next((scope for scope in scopes if source.path == scope
                                  or source.path.startswith(scope.rstrip("/") + "/")
                                  or source_symbol and source_symbol.name == scope), None)
            if scopes and matched_scope is None:
                continue
            if len(scopes) > 1 and per_scope.get(matched_scope, 0) >= max(1, 12 // len(scopes)):
                continue
            per_scope[matched_scope] = per_scope.get(matched_scope, 0) + 1
            declaration = next((anchors[i] for i in relationship.evidence_ids if i in anchors
                                and anchors[i].start_line is not None), None)
            relationships.append({"relationship_id": relationship.id, "source_id": relationship.source_id,
                "target_id": relationship.target_id, "dependency_type": relationship.kind,
                "source_path": source.path, "target_path": target.path,
                "declaration_line": declaration.start_line if declaration else None,
                "navigation_only": True})
            if len(relationships) == 12:
                break
        context["dependency_navigation"] = relationships
        context["dependency_navigation_notice"] = (
            "Indexed internal relations are navigation, not inspected evidence or proof of impact. "
            "Select a relation relevant to the original question; use list_relationships and inspect its "
            "declaration, consumer behavior and target contract. If no relation answers a cross-service "
            "question, retain that coverage gap rather than inventing a none edge or substituting another question.")
        if state["evaluation"]:
            refs = {r.id: r for r in self.references()}
            reads = []
            for assessment in state["evaluation"].dependency_assessments:
                for link in assessment.dependencies:
                    for identifier in (link.source_id, link.target_id):
                        symbol = symbols.get(identifier)
                        source = files.get(symbol.file_id if symbol else identifier)
                        if source is None or not source.line_count:
                            continue
                        start = symbol.start_line if symbol else 1
                        end = min(symbol.end_line if symbol else source.line_count,
                                  start + self.tools.limits.max_source_lines - 1)
                        if any(r.kind == "source" and r.file_id == source.id
                               and r.start_line <= start and r.end_line >= end for r in refs.values()):
                            continue
                        read = {"tool": "get_source_excerpt", "arguments": {
                            "path": source.path, "start_line": start, "end_line": end}}
                        if read not in reads:
                            reads.append(read)
            if reads:
                context["next_source_reads"] = reads[:6]
        return context

    async def evaluate_evidence(self, state):
        # Exploration may stop on the soft closing reservation; evaluation still
        # passes through the unchanged hard request/token/deadline admission.
        closing_stop = self.stop if self._closing_budget_reserved and self.stop == "token_limit" else ""
        if closing_stop:
            self.stop = ""
        try:
            update = await super().evaluate_evidence(state)
        finally:
            if closing_stop:
                self.stop = closing_stop
        previous, current = state["evaluation"], update["evaluation"]
        if previous and current:
            update["evaluation"] = current.model_copy(update={"dependency_assessments": retain_previous(
                current.dependency_assessments, previous.dependency_assessments,
            )})
        current = update["evaluation"]
        if current:
            self._prepare_validation()
            gaps = []
            progress = []
            for assessment in current.dependency_assessments:
                normalized = self._normalize_assessment(assessment, {h.id for h in current.hypotheses})
                if normalized.validation_issues:
                    gaps.append(f"Assessment {assessment.id}: repair dependency IDs, declaration and endpoint source support ({', '.join(normalized.validation_issues)}). Use delivered IDs if available; otherwise inspect the missing endpoints or retain an inconclusive assessment.")
                    # Only relevant endpoint source coverage constitutes progress;
                    # unrelated searches or newly named assessment IDs do not.
                    endpoint_files = {c.file_id for d in normalized.dependencies for c in (d.source, d.target)}
                    coverage = sorted({(r.file_id, r.start_line, r.end_line) for r in self.references()
                                       if r.kind == "source" and r.file_id in endpoint_files})
                    progress.append((assessment.hypothesis_id, sorted(normalized.validation_issues), coverage))
            if gaps:
                missing = list(dict.fromkeys([*current.missing_information, *gaps]))
                update["evaluation"] = current.model_copy(update={"sufficient": False, "missing_information": missing})
                update["missing_information"] = missing
                fingerprint = json.dumps(sorted(progress, key=str))
                if fingerprint == self._last_blocked_progress and not self.stop:
                    self.stop = "no_investigation_progress"
                    self.issues.append("Dependency repair made no relevant endpoint/validation progress; exploration stopped to preserve critical review.")
                self._last_blocked_progress = fingerprint
            else:
                self._last_blocked_progress = None
        return update

    def _prepare_validation(self):
        snapshot = self.tools.accessible_snapshot
        self._files = {f.id: f for f in snapshot.files}
        self._symbols = {s.id: s for s in snapshot.symbols}
        self._relationships = {r.id: r for r in snapshot.relationships}
        self._snapshot_evidence = {e.id: e for e in snapshot.evidence}
        self._references = {r.id: r for r in self.references()}

    def _component(self, identifier):
        symbol = self._symbols.get(identifier)
        source = self._files.get(symbol.file_id if symbol else identifier)
        if source is None:
            return None
        return ComponentReference(id=identifier, file_id=source.id, path=source.path,
                                  symbol_name=symbol.qualified_name if symbol else None)

    def _own_source(self, record, component):
        if record.kind != "source" or record.file_id != component.file_id:
            return False
        symbol = self._symbols.get(component.id)
        return symbol is None or record.start_line <= symbol.end_line and record.end_line >= symbol.start_line

    def _resolve_evidence(self, identifiers):
        evidence = [self._references[i] for i in dict.fromkeys(identifiers) if i in self._references]
        evidence, mismatch = self.verify_references(evidence)
        issues = []
        if set(identifiers) - self._references.keys():
            issues.append("unknown_evidence_ids")
        if mismatch:
            issues.append("commit_mismatch")
        return evidence, issues

    def _normalize_link(self, link):
        source, target = self._component(link.source_id), self._component(link.target_id)
        if source is None or target is None:
            return None
        evidence, issues = self._resolve_evidence(link.evidence_ids)
        relationship = self._relationships.get(link.relationship_id)
        if relationship is None:
            issues.append("relationship_unavailable_or_unresolved")
        elif (relationship.source_id != link.source_id or relationship.target_id != link.target_id
              or relationship.kind != link.dependency_type or relationship.kind == "contains"
              or relationship.resolution != "internal"):
            issues.append("relationship_endpoints_kind_or_resolution_mismatch")
        else:
            # Require the actual dependency declaration, not an unrelated source
            # excerpt somewhere in its originating file or graph metadata alone.
            anchors = [self._snapshot_evidence[i] for i in relationship.evidence_ids if i in self._snapshot_evidence]
            anchored = any(r.kind == "source" and r.file_id == anchor.file_id
                           and anchor.start_line is not None and r.start_line <= anchor.start_line
                           and r.end_line >= (anchor.end_line or anchor.start_line)
                           for r in evidence for anchor in anchors)
            if not anchored:
                issues.append("dependency_declaration_not_inspected")
        if not any(self._own_source(r, source) for r in evidence):
            issues.append("source_component_not_inspected")
        if not any(self._own_source(r, target) for r in evidence):
            issues.append("target_contract_or_implementation_not_inspected")
        return InvestigatedDependency(
            **link.model_dump(exclude={"evidence_ids", "relationship_id"}),
            relationship_id=relationship.id if relationship else None, evidence_ids=[r.id for r in evidence],
            source=source, target=target, evidence=evidence,
            validation_status="insufficient_evidence" if issues else "source_backed", validation_issues=issues,
        )

    def _normalize_assessment(self, assessment, hypotheses):
        issues = []
        dependencies = []
        seen = set()
        if len(assessment.dependencies) > self.config.max_relationships_per_assessment:
            issues.append("relationship_count_limit")
        for link in assessment.dependencies[:self.config.max_relationships_per_assessment]:
            normalized = self._normalize_link(link)
            if link.id in seen:
                issues.append("duplicate_dependency_id")
            seen.add(link.id)
            if normalized is None:
                issues.append("unknown_component_id")
            else:
                dependencies.append(normalized)
                if normalized.validation_issues:
                    issues.append("dependency_not_verified")
        if assessment.hypothesis_id not in hypotheses:
            issues.append("unknown_impact_hypothesis")
        path = assessment.dependency_path
        path_issues = []
        if path:
            if not 1 <= len(path) - 1 <= self.config.max_dependency_depth:
                path_issues.append("dependency_depth_limit_or_invalid_path")
            pairs = {(d.source_id, d.target_id) for d in dependencies if d.validation_status == "source_backed"}
            if any((a, b) not in pairs for a, b in pairwise(path)):
                path_issues.append("path_hop_not_verified")
        issues.extend(path_issues)
        ids = [*assessment.supporting_evidence_ids, *assessment.contradicting_evidence_ids,
               *assessment.demonstration_evidence_ids, *[i for d in dependencies for i in d.evidence_ids]]
        evidence, evidence_issues = self._resolve_evidence(ids)
        issues.extend(evidence_issues)
        supporting = [self._references[i] for i in assessment.supporting_evidence_ids if i in self._references]
        if not dependencies:
            issues.append("verified_dependency_required")
        if assessment.impact_kind in ("demonstrated", "plausible_risk", "none"):
            if not (assessment.consequence.strip() and assessment.change_scenario.strip()
                    and assessment.propagation_explanation.strip() and assessment.contract_analysis.strip()):
                issues.append("concrete_change_scenario_contract_and_consequence_required")
            # A consequence must be grounded at each endpoint, not merely at an import.
            endpoints = {c.id: c for d in dependencies for c in (d.source, d.target)}
            if not endpoints or any(not any(self._own_source(r, c) for r in supporting) for c in endpoints.values()):
                issues.append("impact_requires_endpoint_source_evidence")
        if assessment.impact_kind == "demonstrated":
            demonstration = [self._references[i] for i in assessment.demonstration_evidence_ids if i in self._references]
            if not assessment.demonstration_rationale.strip() or not any(r.kind == "source" for r in demonstration):
                issues.append("demonstrated_impact_requires_separate_grounding")
        return InvestigatedImpact(
            **assessment.model_dump(exclude={"dependencies", "dependency_path", "impact_kind", "uncertainty",
                "supporting_evidence_ids", "contradicting_evidence_ids", "demonstration_evidence_ids"}),
            dependencies=dependencies, dependency_path=[] if path_issues else path,
            impact_kind="inconclusive" if issues else assessment.impact_kind,
            uncertainty="high" if issues else assessment.uncertainty,
            supporting_evidence_ids=[i for i in assessment.supporting_evidence_ids if i in self._references],
            contradicting_evidence_ids=[i for i in assessment.contradicting_evidence_ids if i in self._references],
            demonstration_evidence_ids=[i for i in assessment.demonstration_evidence_ids if i in self._references],
            evidence=evidence, is_cycle=bool(path and not path_issues and path[0] == path[-1]),
            validation_status="insufficient_evidence" if issues else "source_backed",
            validation_issues=list(dict.fromkeys(issues)),
        )

    def finalize(self, state):
        result = super().finalize(state)["result"]
        self._prepare_validation()
        evaluation = state["evaluation"]
        assessments = []
        seen = set()
        for assessment in evaluation.dependency_assessments if evaluation else []:
            if assessment.id in seen:
                assessments = [a.model_copy(update={"impact_kind": "inconclusive", "uncertainty": "high",
                    "validation_status": "insufficient_evidence", "validation_issues": [*a.validation_issues, "duplicate_assessment_id"]})
                    if a.id == assessment.id else a for a in assessments]
                continue
            seen.add(assessment.id)
            assessments.append(self._normalize_assessment(assessment, {h.id for h in result.hypotheses}))
        by_id = {a.id: a for a in assessments}
        missing = list(result.missing_information)
        for assessment in assessments:
            if assessment.validation_issues or assessment.impact_kind == "inconclusive":
                missing.append(f"Assessment {assessment.id}: dependency impact remains inconclusive ({', '.join(assessment.validation_issues) or 'missing causal evidence'}).")
        assessments = [a.model_copy(update={
            "consequence": f"Unverified model interpretation: {a.consequence}",
            "propagation_explanation": f"Unverified model interpretation: {a.propagation_explanation}",
        }) if a.validation_status != "source_backed" or a.impact_kind == "inconclusive" else a for a in assessments]
        findings = []
        for finding in result.findings:
            linked = [by_id[i] for i in finding.assessment_ids if i in by_id]
            invalid = (finding.basis != "consequence_evidence" or len(linked) != len(finding.assessment_ids)
                       or any(a.validation_status != "source_backed" or a.impact_kind not in ("demonstrated", "plausible_risk")
                              for a in linked))
            required = {i for a in linked for i in [*a.supporting_evidence_ids, *a.demonstration_evidence_ids,
                                                   *[i for d in a.dependencies for i in d.evidence_ids]]}
            if not required <= set(finding.evidence_ids):
                invalid = True
            if invalid:
                missing.append(f"Finding {finding.id}: valid dependency assessments and causal source evidence are required.")
                finding = finding.model_copy(update={
                    "validation_status": "insufficient_evidence", "confidence": 0,
                    "review_rationale": "Dependency-impact host validation failed: require verified dependencies, bounded connected paths, endpoint source citations and concrete change consequences; metrics, cycles, interfaces or transitivity alone are not proof of harm.",
                })
            findings.append(finding)
        components = {c.id: c for a in assessments for d in a.dependencies for c in (d.source, d.target)}
        review = state["review"]
        judgments = review.hypotheses if isinstance(review, DependencyImpactReview) else []
        hypotheses = []
        for hypothesis in result.hypotheses:
            if hypothesis.status in {"confirmed", "discarded"}:
                matches = [j for j in judgments if j.hypothesis_id == hypothesis.id]
                judgment = matches[0] if len(matches) == 1 else None
                linked = [by_id[i] for i in judgment.assessment_ids if i in by_id] if judgment else []
                allowed = {"none"} if hypothesis.status == "discarded" else {"demonstrated", "plausible_risk"}
                required = set(hypothesis.evidence_ids)
                valid = (judgment and judgment.status == "supported" and judgment.scope_supported
                         and not judgment.unverified_claims and required and linked
                         and len(linked) == len(set(judgment.assessment_ids))
                         and all(a.hypothesis_id == hypothesis.id and a.validation_status == "source_backed"
                                 and a.impact_kind in allowed for a in linked)
                         and required <= set(judgment.checked_evidence_ids)
                         and set(judgment.checked_evidence_ids) <= self._references.keys()
                         and required <= {e.id for a in linked for e in a.evidence})
                if not valid:
                    reason = "Dependency hypothesis requires independently reviewed scope and valid linked dependency/endpoint/impact evidence."
                    hypothesis = hypothesis.model_copy(update={"status": "inconclusive",
                        "rationale": f"Unverified model interpretation: {hypothesis.rationale}\nHost validation: {reason}"})
                    missing.append(f"Hypothesis {hypothesis.id}: {reason}")
            hypotheses.append(hypothesis)
        if review is None and evaluation:
            missing.append("Complete critical review of dependency-impact conclusions.")
        inconclusive = [a.id for a in assessments if a.impact_kind == "inconclusive"]
        inconclusive.extend(h.id for h in hypotheses if h.status == "inconclusive")
        limitations = [*result.limitations,
            "Only retained resolved internal graph relationships can be host-verified in this version; dynamic, external or unavailable relations remain inconclusive.",
            "Source/graph provenance checks do not prove semantic impact; hypothetical scenarios are risks, not observed historical change propagation.",
        ]
        if any(a.validation_issues for a in assessments):
            limitations.append("Some dependency/impact assessments failed host validation; inspect their per-assessment and per-link validation_issues.")
        return {"result": DependencyImpactResult.model_validate({
            **result.model_dump(), "findings": findings, "components_investigated": list(components.values()),
            "dependency_assessments": assessments, "hypotheses": hypotheses,
            "discarded_hypotheses": [h for h in hypotheses if h.status == "discarded"],
            "critical_review": review, "missing_information": list(dict.fromkeys(missing)),
            "termination_reason": "evidence_validation_failed" if missing and result.termination_reason == "sufficient_evidence" else result.termination_reason,
            "inconclusive_investigations": list(dict.fromkeys(inconclusive)), "limitations": limitations,
        })}


