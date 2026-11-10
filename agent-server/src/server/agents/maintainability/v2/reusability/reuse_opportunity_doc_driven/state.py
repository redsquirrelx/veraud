"""Sequential investigation state."""

from server.runtimes.investigation.state import InvestigationState


class ReuseOpportunityState(InvestigationState, total=False):
    snapshot_hash: str
    current_investigation: int
    pending_queries: list[dict]
    active_query_keys: list[str]
    query_cache: dict
    initial_evidence_loaded: bool
    coverage_recovery_done: bool
    task_limitations: list[str]
    investigation_results: list[dict]
    candidates: list[dict]
    synthesis: dict
    result: dict
    investigation_workspace: dict
