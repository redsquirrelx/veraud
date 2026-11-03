"""Lossless, conservative consolidation of already validated conclusions."""

import json

from .....services.repository_analysis.context import create_identifier
from .schemas import BoundaryCandidateOrigin


def consolidate_candidates(results):
    """Merge only identical claims about identical subjects, never similar prose.

    Local IDs and citations may differ. Every other field must agree, including
    severity/confidence; disagreement is retained as separate provisional work.
    """
    groups = {}
    for result in results:
        for candidate in result.candidates:
            claim = candidate.model_dump(exclude={"id", "evidence_ids"})
            for field in ("components", "symbol_ids", "relationship_ids"):
                claim[field] = sorted(set(claim[field]))
            key = json.dumps(claim, sort_keys=True)
            origin = BoundaryCandidateOrigin(investigation_id=result.investigation_id, candidate_id=candidate.id)
            if key not in groups:
                groups[key] = (candidate.model_copy(deep=True), [])
            retained, origins = groups[key]
            retained = retained.model_copy(update={
                "evidence_ids": list(dict.fromkeys([*retained.evidence_ids, *candidate.evidence_ids]))})
            groups[key] = (retained, origins)
            if origin not in origins:
                origins.append(origin)

    # Model IDs are local to an investigation. Resolve collisions without losing
    # either claim or colliding with a different model-supplied ID.
    reserved = {candidate.id for candidate, _ in groups.values()}
    used, candidates, provenance = set(), [], {}
    for key, (candidate, origins) in groups.items():
        identifier = candidate.id
        if identifier in used:
            identifier = create_identifier("boundary-candidate", key)
            while identifier in reserved or identifier in used:
                identifier = create_identifier("boundary-candidate", identifier, key)
        candidate = candidate.model_copy(update={"id": identifier})
        used.add(identifier)
        candidates.append(candidate)
        provenance[identifier] = origins
    return candidates, provenance
