"""Original/delegated objectives and immutable revision identify plan provenance."""

from typing import TypedDict

from server.contracts.audit import Consumption

from .schemas import (
    AssessmentPlan,
    AssessmentRequest,
    AssessmentResult,
    Assignment,
    InvestigatorCapability,
    InvocationRecord,
    RawInvocation,
)


class ModularityState(TypedDict, total=False):
    request: AssessmentRequest
    repository_id: str
    commit: str | None
    snapshot_hash: str
    investigator_catalog: list[InvestigatorCapability]
    plan: AssessmentPlan | None
    limitations: list[str]
    termination_reason: str
    consumption: Consumption
    initial_plan: list[Assignment]
    execution_records: list[RawInvocation]
    investigation_results: list[InvocationRecord]
    collected_count: int
    result: AssessmentResult
    node_transitions: list[str]
