"""Deterministic consolidation of parametrization investigation results."""

import json

from server.services.repository_analysis.context import create_identifier

from .schemas import (
    ParametrizationInvestigationResult,
)

_SET_FIELDS = (
    "components", "symbol_ids", "relationship_ids", "document_claim_ids",
    "implementations", "consumers", "selected_alternatives",
)


def consolidate_candidates(results: list[ParametrizationInvestigationResult]):
    """Merge identical candidates, never local IDs or similar prose.

    Investigation-local candidate IDs may collide or vary across tasks. Candidate
    content is the identity; each origin remains available through `candidate_origins`.
    """
    groups = {}
    for result in results:
        for candidate in result.candidates:
            claim = candidate.model_dump(exclude={"id", "evidence_ids"})
            for field in _SET_FIELDS:
                if field in claim:
                    claim[field] = sorted(set(claim[field]))
            key = json.dumps(claim, sort_keys=True, default=str)
            if key not in groups:
                groups[key] = (candidate.model_copy(deep=True), [])
            retained, origins_list = groups[key]
            retained = retained.model_copy(update={
                "evidence_ids": list(dict.fromkeys([*retained.evidence_ids, *candidate.evidence_ids]))})
            groups[key] = (retained, origins_list)
            origin = {"investigation_id": result.investigation_id, "candidate_id": candidate.id,
                "evidence_ids": list(candidate.evidence_ids),
                "document_claim_ids": list(candidate.document_claim_ids)}
            if origin not in origins_list:
                origins_list.append(origin)

    reserved = {candidate.id for candidate, _ in groups.values()}
    used, candidates, origins = set(), [], {}
    for key, (candidate, investigations) in groups.items():
        identifier = candidate.id
        if identifier in used:
            identifier = create_identifier("parametrization-candidate", key)
            while identifier in reserved or identifier in used:
                identifier = create_identifier("parametrization-candidate", identifier, key)
        candidate = candidate.model_copy(update={"id": identifier})
        used.add(identifier)
        candidates.append(candidate)
        origins[identifier] = investigations
    return candidates, origins
