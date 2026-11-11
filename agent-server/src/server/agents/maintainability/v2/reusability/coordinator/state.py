"""Original/delegated objectives and immutable revision identify plan provenance."""

from typing import TypedDict

from server.contracts.audit import Consumption

from .schemas import (
    Assignment,
    InvestigatorCapability,
    InvocationRecord,
    RawInvocation,
    ReusabilityPlan,
    ReusabilityRequest,
    ReusabilityResult,
)


class ReusabilityState(TypedDict, total=False):
    request: ReusabilityRequest
    repository_id: str
    commit: str | None
    snapshot_hash: str
    investigator_catalog: list[InvestigatorCapability]
    plan: ReusabilityPlan | None
    limitations: list[str]
    termination_reason: str
    consumption: Consumption
    initial_plan: list[Assignment]
    execution_records: list[RawInvocation]
    investigation_results: list[InvocationRecord]
    collected_count: int
    result: ReusabilityResult
    node_transitions: list[str]
