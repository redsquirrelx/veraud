"""Local sequential investigation state."""

from server.runtimes.investigation.state import InvestigationState

from .schemas import (
    DocumentarySynthesis,
    TestIsolationInvestigationCandidate,
    TestIsolationInvestigationResult,
    TestIsolationToolQuery,
)


class TestIsolationState(InvestigationState, total=False):
    current_investigation: int
    initial_evidence_loaded: bool
    investigation_results: list[TestIsolationInvestigationResult]
    candidates: list[TestIsolationInvestigationCandidate]
    candidate_origins: dict[str, list[dict]]
    documentary_synthesis: DocumentarySynthesis | None
    pending_queries: list[TestIsolationToolQuery]
    query_cache: dict
    active_query_keys: list[str]
    task_limitations: list[str]
