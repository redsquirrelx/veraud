"""Deterministic consolidation of responsibility investigation results."""

import json
from collections import defaultdict
from itertools import combinations

from server.services.repository_analysis.context import create_identifier

from .schemas import (
    ClaimAssessmentComparison,
    ConsolidatedClaimAssessments,
    DocumentarySynthesis,
    DocumentarySynthesisCoverage,
    DocumentarySynthesisIssue,
    LocalClaimAssessment,
    ResponsibilityInvestigationResult,
)


def consolidate_candidates(results: list[ResponsibilityInvestigationResult]):
    grouped = defaultdict(list)
    for result in results:
        for candidate in result.candidates:
            grouped[candidate.id].append(candidate)
    candidates = []
    origins: dict[str, list[dict]] = {}
    for candidate_id in sorted(grouped):
        group = grouped[candidate_id]
        first = group[0]
        merged = first.model_copy(update={
            "evidence_ids": list(dict.fromkeys(v for item in group for v in item.evidence_ids)),
            "components": list(dict.fromkeys(v for item in group for v in item.components)),
            "symbol_ids": list(dict.fromkeys(v for item in group for v in item.symbol_ids)),
            "relationship_ids": list(dict.fromkeys(v for item in group for v in item.relationship_ids)),
            "document_claim_ids": list(dict.fromkeys(v for item in group for v in item.document_claim_ids)),
            "observed_responsibilities": list(dict.fromkeys(
                v for item in group for v in item.observed_responsibilities)),
            "independent_change_reasons": list(dict.fromkeys(
                v for item in group for v in item.independent_change_reasons)),
        })
        candidates.append(merged)
        origins[candidate_id] = [
            {"investigation_id": result.investigation_id, "candidate_id": candidate.id,
             "evidence_ids": list(candidate.evidence_ids),
             "document_claim_ids": list(candidate.document_claim_ids)}
            for result in results for candidate in result.candidates if candidate.id == candidate_id
        ]
    return candidates, origins


def synthesize_documentary(results, plan, evidence=None, snapshot_hash=None):
    """Lossless local observations, not a new evaluation or a global verdict.

    The original documentary record remains at plan.document_claims[claim_id].
    A legacy result without a delivery receipt cannot prove prompt delivery.
    No source or document is read here.
    """
    snapshot_hash = snapshot_hash if snapshot_hash is not None else getattr(plan, "snapshot_hash", None)
    catalog = getattr(plan, "document_claims", {})
    tasks = {task.id: task for task in getattr(plan, "candidates", [])}
    refs = {ref.id: ref for ref in evidence or []}
    selected = {key for task in tasks.values() for key in task.document_claim_ids}
    claims = {key: [] for key in sorted(selected & catalog.keys())}
    rows, anchors, issues, deliveries = {}, {}, {}, {}

    def issue(code, key, investigations, message, assessment_ids=(), reference_ids=()):
        value = DocumentarySynthesisIssue(code=code, claim_id=key,
            investigation_ids=sorted(set(investigations)), assessment_ids=sorted(set(assessment_ids)),
            reference_ids=sorted(set(reference_ids)), message=message)
        issues[value.model_dump_json()] = value

    for key in sorted(selected - catalog.keys()):
        issue("selected_claim_missing_from_catalog", key,
            [task.id for task in tasks.values() if key in task.document_claim_ids],
            "Selected claim has no documentary record.")
    # Sorting is for canonical output only; original conclusions stay untouched.
    for result in sorted(results, key=lambda item: (item.investigation_id, item.model_dump_json())):
        task = tasks.get(result.investigation_id)
        for key, status in result.document_claim_delivery.items():
            deliveries.setdefault((result.investigation_id, key), set()).add(status)
            if key not in catalog or task is None or key not in task.document_claim_ids:
                issue("invalid_claim_delivery_reference", key, [result.investigation_id],
                    "Delivery receipt does not reference a catalogued claim assigned to this task.")
        for assessment in result.claim_assessments:
            key = assessment.claim_id
            content = assessment.model_dump(mode="json", exclude={"assessment_origin"})
            for field in ("code_evidence_ids", "scope_paths", "exceptions_examined"):
                content[field] = sorted(set(content[field]))
            identity = json.dumps(content, sort_keys=True)
            identifier = create_identifier("document-assessment", result.investigation_id, key, identity)
            errors = []
            if key not in catalog:
                errors.append("claim_missing_from_catalog")
            if task is None or key not in task.document_claim_ids:
                errors.append("claim_not_associated_with_investigation")
            if key in catalog and catalog[key].status in {"unmapped"}:
                errors.append("unmapped_documentary_record")
            if key in catalog:
                record = catalog[key]
                if (not record.document_index or not record.claim.evidence or
                    set(record.claim.section_ids) != set(record.section_paths) or
                    {item.section_id for item in record.claim.evidence} != set(record.section_paths) or
                    any(not item.quote for item in record.claim.evidence)):
                    errors.append("invalid_documentary_provenance")
                if assessment.status in {"supported", "contradicted"} and (
                    record.status == "uncertain" or record.claim.certainty != "explicit"
                ):
                    errors.append("uncertain_normative_input")
            if set(assessment.code_evidence_ids) & (catalog.keys() | selected):
                errors.append("documentary_id_used_as_technical_evidence")
            if set(assessment.code_evidence_ids) - refs.keys():
                errors.append("unknown_technical_evidence")
            if set(assessment.code_evidence_ids) - set(result.evidence_ids):
                errors.append("assessment_evidence_not_in_conclusion")
            cited = [refs[ref] for ref in assessment.code_evidence_ids if ref in refs]
            sources = [ref for ref in cited if ref.kind == "source"]
            if set(assessment.scope_paths) - {ref.path for ref in sources}:
                errors.append("assessment_scope_without_source")
            if assessment.status in {"supported", "contradicted"} and (not sources or not assessment.scope_paths):
                errors.append("assessment_requires_source")
            if assessment.code_evidence_ids and not sources:
                errors.append("assessment_requires_source")
            if any(not ref.content_hash or not ref.tool_call_id
                or (snapshot_hash is not None and ref.snapshot_hash != snapshot_hash)
                or (ref.commit and ref.commit_verification not in {"exact", "line_endings_equivalent"})
                or (ref.kind == "source" and (not ref.start_line or not ref.end_line)) for ref in cited):
                errors.append("unverified_technical_provenance")
            if key in catalog and catalog[key].document_index and any(
                ref.commit != catalog[key].document_index.commit for ref in cited
            ):
                errors.append("documentary_technical_commit_mismatch")
            delivery = result.document_claim_delivery.get(key, "unknown")
            if delivery in {"unavailable", "not_delivered"} and assessment.assessment_origin == "investigator":
                errors.append("assessment_without_claim_delivery")
            effective = not errors and assessment.assessment_origin != "host_pending" and (
                assessment.assessment_origin == "investigator" or bool(sources))
            row = LocalClaimAssessment(id=identifier, investigation_id=result.investigation_id,
                assessment=assessment, delivery_status=delivery, effective=effective,
                investigation_limitations=sorted(set(result.limitations)), integrity_issues=sorted(set(errors)))
            if identifier in rows:
                issue("duplicate_assessment", key, [result.investigation_id],
                    "Repeated identical local assessment retained once; original conclusions remain available.", [identifier])
                previous = rows[identifier]
                row = previous.model_copy(update={
                    "investigation_limitations": sorted(set(previous.investigation_limitations + row.investigation_limitations)),
                    "integrity_issues": sorted(set(previous.integrity_issues + row.integrity_issues)),
                    "effective": previous.effective and row.effective})
            rows[identifier] = row
            anchors.setdefault(identifier, set()).add(tuple(sorted(set(result.relationship_ids))))
            for error in errors:
                issue(error, key, [result.investigation_id], "Local assessment retained but excluded from effective coverage.",
                    [identifier], assessment.code_evidence_ids)

    for (investigation_id, key), statuses in deliveries.items():
        if len(statuses) > 1:
            issue("inconsistent_claim_delivery", key, [investigation_id],
                "Conflicting delivery receipts; delivery cannot be confirmed.")
    for identifier, row in list(rows.items()):
        statuses = deliveries.get((row.investigation_id, row.assessment.claim_id), set())
        if len(statuses) > 1:
            row = row.model_copy(update={"delivery_status": "unknown", "effective": False,
                "integrity_issues": sorted({*row.integrity_issues, "inconsistent_claim_delivery"})})
            rows[identifier] = row
        if row.assessment.claim_id in catalog:
            claims.setdefault(row.assessment.claim_id, []).append(row)

    summaries = {}
    for key, local in sorted(claims.items()):
        local.sort(key=lambda row: (row.investigation_id, row.id))
        for investigation_id in sorted({row.investigation_id for row in local}):
            repeated = [row for row in local if row.investigation_id == investigation_id]
            if len(repeated) > 1:
                issue("multiple_assessments_in_investigation", key, [investigation_id],
                    "Different assessments for the same claim/task are preserved; invalid multiplicity requires review.",
                    [row.id for row in repeated])
                for row in repeated:
                    updated = row.model_copy(update={"effective": False,
                        "integrity_issues": sorted({*row.integrity_issues, "multiple_assessments_in_investigation"})})
                    local[local.index(row)] = rows[row.id] = updated
        effective = [row for row in local if row.effective]
        comparisons = []
        for left, right in combinations(effective, 2):
            statuses = {left.assessment.status, right.assessment.status}
            if len(statuses) < 2 or "inconclusive" in statuses:
                continue
            a, b = set(left.assessment.scope_paths), set(right.assessment.scope_paths)
            left_source = [refs[key] for key in left.assessment.code_evidence_ids
                if key in refs and refs[key].kind == "source" and refs[key].path in a]
            right_source = [refs[key] for key in right.assessment.code_evidence_ids
                if key in refs and refs[key].kind == "source" and refs[key].path in b]
            ranges_overlap = any(x.path == y.path and x.start_line <= y.end_line and y.start_line <= x.end_line
                for x in left_source for y in right_source)
            if a and b and a.isdisjoint(b):
                relation = "different_scopes"
                limitation = "Different local file scopes; differing outcomes do not imply logical conflict or global compliance."
            elif left_source and right_source and not ranges_overlap:
                relation = "different_scopes"
                limitation = "Cited source windows are disjoint; file-name equality does not establish the same examined interaction."
            elif a and a == b and anchors[left.id] == anchors[right.id] and any(anchors[left.id]) and ranges_overlap:
                relation = "same_technical_anchors"
                limitation = "Potential incompatibility at equal file scopes and task-level relationship anchors. These are not claim-specific interactions; exceptions and finer scope require review."
            else:
                relation = "overlapping_or_unknown"
                limitation = "File overlap/equality alone cannot identify the same interaction. Outcomes remain local and scope comparability is uncertain."
            comparisons.append(ClaimAssessmentComparison(assessment_ids=[left.id, right.id],
                scope_relation=relation, limitation=limitation))
        record = catalog[key]
        limitations = ["Only observed local evaluations are consolidated; no explicit whole-claim completeness rule is available."]
        if any(not row.assessment.exceptions_examined for row in local):
            limitations.append("One or more evaluations have no recorded exception check; this does not establish absence of exceptions.")
        if any(row.delivery_status == "unknown" for row in local):
            limitations.append("Prompt delivery was not recorded or cannot be confirmed for one or more evaluations.")
        if record.status != "applicable":
            limitations.append("Documentary mapping limitations remain in plan.document_claims for this claim: " + record.reason)
        summaries[key] = ConsolidatedClaimAssessments(claim_id=key, assessments=local,
            selected_investigation_ids=sorted(task.id for task in tasks.values() if key in task.document_claim_ids),
            evaluated_investigation_ids=sorted({row.investigation_id for row in effective}),
            has_contradiction=any(row.assessment.status == "contradicted" for row in effective),
            has_inconclusive=any(row.assessment.status == "inconclusive" for row in local),
            coverage_status="partial" if effective else "not_evaluated", comparisons=comparisons, limitations=limitations)

    valid = [row for group in summaries.values() for row in group.assessments if row.effective]
    evaluated = {row.assessment.claim_id for row in valid}
    def by_status(status):
        return sorted({row.assessment.claim_id for row in valid if row.assessment.status == status})
    delivered = {key for (investigation_id, key), statuses in deliveries.items() if statuses == {"delivered"}
        and key in catalog and investigation_id in tasks and key in tasks[investigation_id].document_claim_ids}
    unknown_delivery = {key for task in tasks.values() for key in task.document_claim_ids
        if deliveries.get((task.id, key), set()) not in ({"delivered"}, {"unavailable"}, {"not_delivered"})}
    return DocumentarySynthesis(claims=summaries,
        unresolved_assessments=sorted((row for row in rows.values() if row.assessment.claim_id not in catalog), key=lambda row: row.id),
        integrity_issues=sorted(issues.values(), key=lambda value: value.model_dump_json()),
        coverage=DocumentarySynthesisCoverage(selected_claim_ids=sorted(selected), delivered_claim_ids=sorted(delivered),
            delivery_unknown_claim_ids=sorted(unknown_delivery), evaluated_claim_ids=sorted(evaluated),
            source_examined_claim_ids=sorted({row.assessment.claim_id for row in valid if row.assessment.code_evidence_ids}),
            contradicted_claim_ids=by_status("contradicted"), locally_supported_claim_ids=by_status("supported"),
            locally_not_applicable_claim_ids=by_status("not_applicable"), inconclusive_claim_ids=by_status("inconclusive"),
            selected_not_evaluated_claim_ids=sorted(selected - evaluated), partially_covered_claim_ids=sorted(evaluated)))
