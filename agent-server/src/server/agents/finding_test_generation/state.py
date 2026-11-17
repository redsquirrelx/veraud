"""LangGraph state for the finding-test generation cycle."""

from typing import TypedDict

from .input_adapter import InputDiagnostics
from .schemas import (
    AuditDocument,
    FindingTestGenerationRequest,
    FindingTestGenerationResult,
    ValidationRecord,
    VerificationSpec,
)


class FindingTestGenerationState(TypedDict, total=False):
    request: FindingTestGenerationRequest
    document: AuditDocument | None
    diagnostics: InputDiagnostics
    baseline_available: bool
    specs: list[VerificationSpec]
    validation_records: list[ValidationRecord]
    limitations: list[str]
    warnings: list[str]
    errors: list[str]
    # Disposable copy of the audited repo for local validation (None when blocked).
    run_root: str
    tool_calls: int
    llm_calls: int
    llm_tokens: int | None
    log_path: str
    green_root: str | None
    green_outcomes: dict[str, str]
    # Candidate test contents per verification; the package step ships these verbatim.
    candidates: list[dict]
    outcomes: dict[str, str]
    verification_results: list
    validation_status: str
    result: FindingTestGenerationResult
