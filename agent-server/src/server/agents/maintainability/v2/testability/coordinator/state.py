"""Original/delegated objectives and immutable revision identify plan provenance."""

from typing import TypedDict

from server.contracts.audit import Consumption

from .schemas import (
    Assignment,
    InvestigatorCapability,
    InvocationRecord,
    RawInvocation,
    TestabilityPlan,
    TestabilityRequest,
    TestabilityResult,
)


class TestabilityState(TypedDict, total=False):
    request: TestabilityRequest
    repository_id: str
    commit: str | None
    snapshot_hash: str
    investigator_catalog: list[InvestigatorCapability]
    plan: TestabilityPlan | None
    limitations: list[str]
    termination_reason: str
    consumption: Consumption
    initial_plan: list[Assignment]
    execution_records: list[RawInvocation]
    investigation_results: list[InvocationRecord]
    collected_count: int
    result: TestabilityResult
    node_transitions: list[str]
