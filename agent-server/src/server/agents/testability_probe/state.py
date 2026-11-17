"""LangGraph state for the TestabilityProbeAgent."""

from typing import TypedDict

from server.agents.testability_probe.input_adapter import InputDiagnostics
from server.agents.testability_probe.schemas import (
    PlannedVerification,
    ProbeDocument,
    ProbeRequest,
    ProbeResult,
    ValidationRecord,
    VerificationResult,
)


class TestabilityProbeState(TypedDict, total=False):
    request: ProbeRequest
    document: ProbeDocument | None
    diagnostics: InputDiagnostics
    baseline_available: bool
    architecture_digest: str
    plans: list[PlannedVerification]
    candidates: list[dict]     # [{verification_id, finding_id, test_path, test_name, content, tool_calls, generated_by, suspicion, attempts}]
    outcomes: dict[str, str]   # verification_id -> backend classification
    assertion_messages: dict[str, str | None]
    validation_records: list[ValidationRecord]
    verification_results: list[VerificationResult]
    limitations: list[str]
    warnings: list[str]
    errors: list[str]
    run_root: str
    green_root: str | None
    green_outcomes: dict[str, str]
    tool_calls: int
    llm_calls: int
    llm_tokens: int | None
    log_path: str
    validation_status: str
    budget_exhausted: bool
    investigation_notes: dict[str, str]
    result: ProbeResult
