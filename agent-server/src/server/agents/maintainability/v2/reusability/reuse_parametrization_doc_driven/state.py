"""Local sequential investigation state for the reuse-parametrization investigator."""

from server.runtimes.investigation.state import InvestigationState

from .schemas import (
    ParametrizationInvestigationResult,
    ParametrizationToolQuery,
)


class ParametrizationState(InvestigationState, total=False):
    current_investigation: int
    pending_queries: list[ParametrizationToolQuery]
    query_cache: dict
    active_query_keys: list[str]
    initial_evidence_loaded: bool
    coverage_recovery_done: bool
    task_limitations: list[str]
    investigation_results: list[ParametrizationInvestigationResult]
