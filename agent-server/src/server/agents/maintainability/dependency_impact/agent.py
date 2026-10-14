"""Source-grounded dependency-impact specialization of the shared LangGraph cycle."""

from itertools import pairwise
from pathlib import Path

from ...modularity_runtime.agent import InvestigationAgent, InvestigationExecution
from .schemas import (
    ComponentReference,
    DependencyImpactConfig,
    DependencyImpactEvaluation,
    DependencyImpactFinding,
    DependencyImpactRequest,
    DependencyImpactResult,
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

    def _context(self, state):
        return super()._context(state) | {"dependency_limits": {
            "max_depth": self.config.max_dependency_depth,
            "max_relationships_per_assessment": self.config.max_relationships_per_assessment,
        }}

    async def evaluate_evidence(self, state):
        update = await super().evaluate_evidence(state)
        previous, current = state["evaluation"], update["evaluation"]
        if previous and current:
            ids = {a.id for a in current.dependency_assessments}
            update["evaluation"] = current.model_copy(update={"dependency_assessments": [
                *current.dependency_assessments, *[a for a in previous.dependency_assessments if a.id not in ids],
            ]})
        return update

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
        if assessment.impact_kind in ("demonstrated", "plausible_risk"):
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
        snapshot = self.tools.accessible_snapshot
        self._files = {f.id: f for f in snapshot.files}
        self._symbols = {s.id: s for s in snapshot.symbols}
        self._relationships = {r.id: r for r in snapshot.relationships}
        self._snapshot_evidence = {e.id: e for e in snapshot.evidence}
        self._references = {r.id: r for r in self.references()}
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
                finding = finding.model_copy(update={
                    "validation_status": "insufficient_evidence", "confidence": 0,
                    "review_rationale": "Dependency-impact host validation failed: require verified dependencies, bounded connected paths, endpoint source citations and concrete change consequences; metrics, cycles, interfaces or transitivity alone are not proof of harm.",
                })
            findings.append(finding)
        components = {c.id: c for a in assessments for d in a.dependencies for c in (d.source, d.target)}
        inconclusive = [a.id for a in assessments if a.impact_kind == "inconclusive"]
        inconclusive.extend(h.id for h in result.hypotheses if h.status == "inconclusive")
        limitations = [*result.limitations,
            "Only retained resolved internal graph relationships can be host-verified in this version; dynamic, external or unavailable relations remain inconclusive.",
            "Source/graph provenance checks do not prove semantic impact; hypothetical scenarios are risks, not observed historical change propagation.",
        ]
        if any(a.validation_issues for a in assessments):
            limitations.append("Some dependency/impact assessments failed host validation; inspect their per-assessment and per-link validation_issues.")
        return {"result": DependencyImpactResult.model_validate({
            **result.model_dump(), "findings": findings, "components_investigated": list(components.values()),
            "dependency_assessments": assessments, "discarded_hypotheses": [h for h in result.hypotheses if h.status == "discarded"],
            "inconclusive_investigations": list(dict.fromkeys(inconclusive)), "limitations": limitations,
        })}


class DependencyImpactAgent(InvestigationAgent):
    request_type = DependencyImpactRequest
    config_type = DependencyImpactConfig
    execution_type = DependencyImpactExecution
    trace_name = "dependency-impact"
    agent_type = "dependency_impact"
