"""Local sequential investigation state."""

from server.runtimes.investigation.state import InvestigationState

from .schemas import (
    DocumentarySynthesis,
    TestControllabilityInvestigationCandidate,
    TestControllabilityInvestigationResult,
    TestControllabilityToolQuery,
)


class TestControllabilityState(InvestigationState, total=False):
    current_investigation: int
    initial_evidence_loaded: bool
    investigation_results: list[TestControllabilityInvestigationResult]
    candidates: list[TestControllabilityInvestigationCandidate]
    candidate_origins: dict[str, list[dict]]
    documentary_synthesis: DocumentarySynthesis | None
    pending_queries: list[TestControllabilityToolQuery]
    query_cache: dict
    active_query_keys: list[str]
    task_limitations: list[str]
