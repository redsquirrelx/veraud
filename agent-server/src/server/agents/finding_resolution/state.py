"""Per-finding investigation state, separate from historical evidence."""

from typing import TypedDict

from server.contracts.audit import Consumption, DeferredProviderStage, Finding
from server.runtimes.repository.schemas import RepositoryToolCall
from server.runtimes.repository.tools import RepositoryToolResponse

from .schemas import FindingInvestigation, FindingInvestigationTurn, VerificationPlan


class FindingResolutionState(TypedDict):
    next_finding: int
    finding: Finding | None
    finding_context: dict
    plans: list[VerificationPlan]
    plan: VerificationPlan | None
    investigations: list[FindingInvestigation]
    query_cache: dict[str, RepositoryToolResponse]
    pending_queries: list[RepositoryToolCall]
    history: list[FindingInvestigationTurn]
    investigation_turns: int
    no_progress_turns: int
    tool_stop: str
    finding_usage_start: Consumption
    issue_start: int
    messages: list
    termination_reason: str
    limitations: list[str]
    consumption: Consumption
    deferred_stages: list[DeferredProviderStage]
