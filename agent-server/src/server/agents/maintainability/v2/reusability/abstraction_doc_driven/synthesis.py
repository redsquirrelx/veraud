"""Deterministic consolidation of abstraction investigation results."""

from collections import defaultdict

from .schemas import AbstractionInvestigationResult


def consolidate_candidates(results: list[AbstractionInvestigationResult]):
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
            "guarantees": list(dict.fromkeys(v for item in group for v in item.guarantees)),
            "implementers": list(dict.fromkeys(v for item in group for v in item.implementers)),
            "consumers": list(dict.fromkeys(v for item in group for v in item.consumers)),
        })
        candidates.append(merged)
        origins[candidate_id] = [
            {"investigation_id": result.investigation_id, "candidate_id": candidate.id,
             "evidence_ids": list(candidate.evidence_ids)}
            for result in results for candidate in result.candidates if candidate.id == candidate_id
        ]
    return candidates, origins


def documentary_coverage(results, plan):
    supported, contradicted, inconclusive = set(), set(), set()
    for result in results:
        for assessment in result.claim_assessments:
            if assessment.status == "supported":
                supported.add(assessment.claim_id)
            elif assessment.status == "contradicted":
                contradicted.add(assessment.claim_id)
            elif assessment.status == "inconclusive":
                inconclusive.add(assessment.claim_id)
    catalog = getattr(plan, "document_claims", {}) if plan else {}
    return {"selected_claims": len(catalog), "supported_claims": len(supported),
        "contradicted_claims": len(contradicted), "inconclusive_claims": len(inconclusive)}
