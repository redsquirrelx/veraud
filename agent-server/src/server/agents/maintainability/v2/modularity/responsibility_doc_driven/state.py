"""Local sequential investigation state."""

from server.runtimes.investigation.state import InvestigationState

from .schemas import (
    DocumentarySynthesis,
    ResponsibilityInvestigationCandidate,
    ResponsibilityInvestigationResult,
    ResponsibilityToolQuery,
)


class ResponsibilityState(InvestigationState, total=False):
    current_investigation: int
    initial_evidence_loaded: bool
    investigation_results: list[ResponsibilityInvestigationResult]
    candidates: list[ResponsibilityInvestigationCandidate]
    candidate_origins: dict[str, list[dict]]
    documentary_synthesis: DocumentarySynthesis | None
    pending_queries: list[ResponsibilityToolQuery]
    query_cache: dict
    active_query_keys: list[str]
    task_limitations: list[str]
