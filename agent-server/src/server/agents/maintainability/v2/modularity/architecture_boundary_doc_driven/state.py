"""Local sequential phase state; evidence remains owned by RepositoryToolset."""

from server.runtimes.investigation.state import InvestigationState

from .schemas import (
    BoundaryCandidate,
    BoundaryCandidateOrigin,
    BoundaryInvestigationResult,
    BoundaryToolQuery,
    DocumentarySynthesis,
)


class BoundaryState(InvestigationState, total=False):
    current_investigation: int
    initial_evidence_loaded: bool
    investigation_results: list[BoundaryInvestigationResult]
    candidates: list[BoundaryCandidate]
    candidate_origins: dict[str, list[BoundaryCandidateOrigin]]
    documentary_synthesis: DocumentarySynthesis
    pending_queries: list[BoundaryToolQuery]
    query_cache: dict[str, dict]
    active_query_keys: list[str]
    task_budget: dict
    task_limitations: list[str]
    no_progress_turns: int
    consumption: dict
    next_phase: str | None
