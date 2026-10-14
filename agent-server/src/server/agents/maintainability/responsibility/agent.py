"""Cohesion auditor: shared cognitive graph, specialized evidence and finalization rules."""

from pathlib import Path

from ...modularity_runtime.agent import InvestigationAgent, InvestigationExecution
from .schemas import (
    InvestigatedComponent,
    ResponsibilityConfig,
    ResponsibilityEvaluation,
    ResponsibilityFinding,
    ResponsibilityRequest,
    ResponsibilityResult,
)


class ResponsibilityExecution(InvestigationExecution):
    trace_name = "responsibility"
    tool_prefix = "responsibility"
    prompt_directory = Path(__file__).parent / "prompts"
    evaluation_schema = ResponsibilityEvaluation
    finding_schema = ResponsibilityFinding
    result_schema = ResponsibilityResult

    async def evaluate_evidence(self, state):
        update = await super().evaluate_evidence(state)
        previous, current = state["evaluation"], update["evaluation"]
        if previous and current:
            ids = {a.id for a in current.component_assessments}
            current = current.model_copy(update={"component_assessments": [
                *current.component_assessments, *[a for a in previous.component_assessments if a.id not in ids],
            ]})
            update["evaluation"] = current
        return update

    def finalize(self, state):
        result = super().finalize(state)["result"]
        evaluation = state["evaluation"]
        if evaluation is None:
            return {"result": result.model_copy(update={
                "discarded_hypotheses": [h for h in result.hypotheses if h.status == "discarded"],
                "inconclusive_investigations": [h.id for h in result.hypotheses if h.status == "inconclusive"],
            })}
        snapshot = self.tools.accessible_snapshot
        files = {f.id: f for f in snapshot.files}
        symbols = {s.id: s for s in snapshot.symbols}
        references = {r.id: r for r in self.references()}
        components = []
        limitations = list(result.limitations)
        omitted = []
        seen = set()
        for assessment in evaluation.component_assessments:
            if assessment.id in seen:
                limitations.append("Duplicate component assessment omitted; its findings cannot be accepted.")
                # Invalidate the earlier entry too; never silently select one interpretation.
                components = [c.model_copy(update={"validation_status": "insufficient_evidence", "cohesion": "inconclusive",
                              "validation_issues": [*c.validation_issues, "duplicate_assessment_id"]})
                              if c.id == assessment.id else c for c in components]
                continue
            seen.add(assessment.id)
            symbol = symbols.get(assessment.component_id)
            file_id = symbol.file_id if symbol else assessment.component_id
            source = files.get(file_id)
            if source is None:
                limitations.append(f"Assessment {assessment.id} omitted: unknown component ID.")
                omitted.append(assessment.id)
                continue
            ids = list(assessment.evidence_ids)
            for responsibility in assessment.responsibilities:
                ids.extend(responsibility.supporting_evidence_ids)
                ids.extend(responsibility.contradicting_evidence_ids)
            evidence = [references[i] for i in dict.fromkeys(ids) if i in references]
            evidence, mismatch = self.verify_references(evidence)
            issues = []
            if set(ids) - references.keys():
                issues.append("unknown_evidence_ids")
            if mismatch:
                issues.append("commit_mismatch")

            def own_source(record, file_id=file_id, symbol=symbol):
                return (record.kind == "source" and record.file_id == file_id
                        and (symbol is None or record.start_line <= symbol.end_line
                             and record.end_line >= symbol.start_line))

            if not any(own_source(r) for r in evidence):
                issues.append("component_source_not_inspected")
            responsibility_ids = {r.id for r in assessment.responsibilities}
            if len(responsibility_ids) != len(assessment.responsibilities):
                issues.append("duplicate_responsibility_ids")
            if not assessment.responsibilities:
                issues.append("responsibilities_not_established")
            for responsibility in assessment.responsibilities:
                supporting = [references[i] for i in responsibility.supporting_evidence_ids if i in references]
                if not responsibility.behaviors or not any(own_source(r) for r in supporting):
                    issues.append("responsibility_requires_observed_behavior_and_own_source")
            for conflict in assessment.potentially_incompatible:
                if (len(set(conflict.responsibility_ids)) < 2
                        or not set(conflict.responsibility_ids) <= responsibility_ids):
                    issues.append("invalid_conflict_responsibility_ids")
                for responsibility in assessment.responsibilities:
                    if responsibility.id in conflict.responsibility_ids and not responsibility.possible_change_reasons:
                        issues.append("independent_change_reasons_missing")
            if assessment.cohesion == "mixed" and not assessment.potentially_incompatible:
                issues.append("mixed_responsibilities_require_explained_conflict")
            # Never expose fabricated IDs as citations, even on an inconclusive assessment.
            responsibilities = [r.model_copy(update={
                "supporting_evidence_ids": [i for i in r.supporting_evidence_ids if i in references],
                "contradicting_evidence_ids": [i for i in r.contradicting_evidence_ids if i in references],
            }) for r in assessment.responsibilities]
            components.append(InvestigatedComponent(
                **assessment.model_dump(exclude={"responsibilities", "cohesion", "evidence_ids"}),
                responsibilities=responsibilities, cohesion="inconclusive" if issues else assessment.cohesion,
                evidence_ids=[r.id for r in evidence], path=source.path, file_id=file_id,
                symbol_name=symbol.qualified_name if symbol else None, evidence=evidence,
                validation_status="insufficient_evidence" if issues else "source_backed",
                validation_issues=list(dict.fromkeys(issues)),
            ))
        by_id = {c.id: c for c in components}
        findings = []
        for finding in result.findings:
            linked = [by_id[i] for i in finding.assessment_ids if i in by_id]
            invalid = (finding.basis != "behavioral" or len(linked) != len(finding.assessment_ids)
                       or any(c.validation_status != "source_backed" or c.cohesion != "mixed" for c in linked))
            for component in linked:
                required = {i for r in component.responsibilities for i in r.supporting_evidence_ids}
                if not required <= set(finding.evidence_ids):
                    invalid = True
            if invalid:
                finding = finding.model_copy(update={
                    "validation_status": "insufficient_evidence", "confidence": 0,
                    "review_rationale": "Responsibility host validation failed: require behavioral evidence, verified component assessments, explained independent responsibilities and linked source citations; metrics/names alone are not proof.",
                })
            findings.append(finding)
        inconclusive = [c.id for c in components if c.cohesion == "inconclusive"]
        inconclusive.extend(omitted)
        inconclusive.extend(h.id for h in result.hypotheses if h.status == "inconclusive")
        if any(c.validation_issues for c in components):
            limitations.append("Some inferred responsibilities failed source/identity/commit validation; these component assessments remain inconclusive.")
        return {"result": ResponsibilityResult.model_validate({
            **result.model_dump(), "findings": findings, "components_investigated": components,
            "discarded_hypotheses": [h for h in result.hypotheses if h.status == "discarded"],
            "inconclusive_investigations": list(dict.fromkeys(inconclusive)),
            "limitations": limitations,
        })}


class ResponsibilityAgent(InvestigationAgent):
    request_type = ResponsibilityRequest
    config_type = ResponsibilityConfig
    execution_type = ResponsibilityExecution
    trace_name = "responsibility"
    agent_type = "responsibility"
