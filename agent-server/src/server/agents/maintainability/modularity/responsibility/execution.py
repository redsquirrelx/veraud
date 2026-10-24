"""Cohesion auditor: shared cognitive graph, specialized evidence and finalization rules."""

from pathlib import Path

from .....runtimes.investigation.agent import InvestigationExecution
from .....runtimes.investigation.records import retain_previous
from .schemas import (
    InvestigatedComponent,
    ResponsibilityEvaluation,
    ResponsibilityFinding,
    ResponsibilityResult,
    ResponsibilityReview,
)


class ResponsibilityExecution(InvestigationExecution):
    trace_name = "responsibility"
    tool_prefix = "responsibility"
    prompt_directory = Path(__file__).parent / "prompts"
    evaluation_schema = ResponsibilityEvaluation
    finding_schema = ResponsibilityFinding
    result_schema = ResponsibilityResult
    review_schema = ResponsibilityReview

    async def evaluate_evidence(self, state):
        update = await super().evaluate_evidence(state)
        previous, current = state["evaluation"], update["evaluation"]
        if previous and current:
            current = current.model_copy(update={"component_assessments": retain_previous(
                current.component_assessments, previous.component_assessments,
            )})
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
        missing = list(result.missing_information)
        unresolved = []
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
            # Recover only exact, unambiguous file paths. Never guess a file from a
            # directory name, assessment label, or one of its citations.
            path_matches = [f.id for f in snapshot.files if f.path == assessment.component_id]
            component_id = path_matches[0] if len(path_matches) == 1 else assessment.component_id
            symbol = symbols.get(component_id)
            file_id = symbol.file_id if symbol else component_id
            source = files.get(file_id)
            if source is None:
                reason = f"Assessment {assessment.id}: unknown component ID; provide an exact file/symbol ID and inspect its behavior."
                limitations.append(reason)
                missing.append(reason)
                unresolved.append(assessment.model_copy(update={
                    "cohesion": "inconclusive",
                    "evidence_ids": [i for i in assessment.evidence_ids if i in references],
                    "responsibilities": [r.model_copy(update={
                        "supporting_evidence_ids": [i for i in r.supporting_evidence_ids if i in references],
                        "contradicting_evidence_ids": [i for i in r.contradicting_evidence_ids if i in references],
                    }) for r in assessment.responsibilities],
                }))
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
                **assessment.model_dump(exclude={"component_id", "responsibilities", "cohesion", "evidence_ids"}),
                component_id=component_id,
                responsibilities=responsibilities, cohesion="inconclusive" if issues else assessment.cohesion,
                evidence_ids=[r.id for r in evidence], path=source.path, file_id=file_id,
                symbol_name=symbol.qualified_name if symbol else None, evidence=evidence,
                validation_status="insufficient_evidence" if issues else "source_backed",
                validation_issues=list(dict.fromkeys(issues)),
            ))
        by_id = {c.id: c for c in components}
        for component in components:
            if component.cohesion == "inconclusive":
                missing.append(f"Assessment {component.id}: complete behavioral validation ({', '.join(component.validation_issues) or 'cohesion unresolved'}).")
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
        review = state["review"]
        judgments = review.hypotheses if isinstance(review, ResponsibilityReview) else []
        hypotheses = []
        for hypothesis in result.hypotheses:
            if hypothesis.status in {"confirmed", "discarded"}:
                matches = [j for j in judgments if j.hypothesis_id == hypothesis.id]
                judgment = matches[0] if len(matches) == 1 else None
                linked = [by_id[i] for i in judgment.assessment_ids if i in by_id] if judgment else []
                required = set(hypothesis.evidence_ids)
                valid = (judgment and judgment.status == "supported" and judgment.scope_supported
                         and not judgment.unverified_claims and required
                         and required <= set(judgment.checked_evidence_ids)
                         and set(judgment.checked_evidence_ids) <= references.keys()
                         and linked and len(linked) == len(set(judgment.assessment_ids))
                         and all(c.validation_status == "source_backed" and c.cohesion != "inconclusive" for c in linked)
                         and required <= {i for c in linked for i in c.evidence_ids})
                if not valid:
                    reason = "Responsibility hypothesis scope was not independently verified against valid component assessments; retain local observations only."
                    hypothesis = hypothesis.model_copy(update={
                        "status": "inconclusive",
                        "rationale": f"Unverified model interpretation: {hypothesis.rationale}\nHost validation: {reason}",
                    })
                    missing.append(f"Hypothesis {hypothesis.id}: {reason}")
            hypotheses.append(hypothesis)
        if review is None:
            missing.append("Complete critical review of responsibility conclusions; execution ended before review was available.")
        inconclusive = [c.id for c in components if c.cohesion == "inconclusive"]
        inconclusive.extend(omitted)
        inconclusive.extend(h.id for h in hypotheses if h.status == "inconclusive")
        if any(c.validation_issues for c in components):
            limitations.append("Some inferred responsibilities failed source/identity/commit validation; these component assessments remain inconclusive.")
        return {"result": ResponsibilityResult.model_validate({
            **result.model_dump(), "findings": findings, "components_investigated": components,
            "hypotheses": hypotheses,
            "discarded_hypotheses": [h for h in hypotheses if h.status == "discarded"],
            "unresolved_component_assessments": unresolved,
            "critical_review": review,
            "missing_information": list(dict.fromkeys(missing)),
            "termination_reason": "evidence_validation_failed" if missing and result.termination_reason == "sufficient_evidence" else result.termination_reason,
            "inconclusive_investigations": list(dict.fromkeys(inconclusive)),
            "limitations": limitations,
        })}


