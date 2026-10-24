"""Modularity contract bindings for the shared deterministic synthesis helpers."""

from .....runtimes.coordination import synthesis as shared
from .....runtimes.coordination.synthesis import (  # noqa: F401 - established public helpers
    actionable,
    evidence_index,
    evidence_key,
    normalized,
    request_key,
    semantic_key,
    stable_id,
)
from .schemas import ConsolidatedFinding, EvidenceGap, FindingContribution


def finding_index(records):
    return shared.finding_index(records, FindingContribution)


def detect_contradictions(records, withdrawn):
    return shared.detect_contradictions(records, withdrawn, gap_type=EvidenceGap, contribution_type=FindingContribution)


def consolidate(records, proposed_groups, gaps, withdrawn):
    return shared.consolidate(records, proposed_groups, gaps, withdrawn,
        contribution_type=FindingContribution, consolidated_type=ConsolidatedFinding, id_prefix="modularity-finding")
