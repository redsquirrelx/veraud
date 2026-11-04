from types import SimpleNamespace

import pytest

from config.agents.audit import (
    AuditAgentDefaults,
    AuditCallLimits,
    apply_audit_call_limits,
    apply_audit_defaults,
)
from server.agents.maintainability.manager.config import MaintainabilityConfig
from server.agents.maintainability.manager.validation import validate_call_capacity
from server.services.audit_diagnostics import execution_diagnostics
from server.services.execution_failures import (
    ExecutionValidationError,
    failure_from_exception,
)


def test_hierarchy_call_envelopes_reserve_full_initial_wave():
    limits = apply_audit_defaults(MaintainabilityConfig(), AuditAgentDefaults(max_model_calls=30))
    validate_call_capacity(limits, SimpleNamespace(dimensions=["modularity", "reusability"]))
    limits = apply_audit_call_limits(limits, AuditCallLimits(manager={"max_model_calls": 400},
        coordinator={"max_model_calls": 160}, investigator={"max_model_calls": 40}))
    validate_call_capacity(limits, SimpleNamespace(dimensions=["modularity", "reusability"]))
    assert limits.invocation_limits.invocation_limits.max_model_calls == 40
    undersized = apply_audit_call_limits(limits, AuditCallLimits(coordinator={"max_model_calls": 40}))
    with pytest.raises(ValueError, match="coordinator_call_budget_too_small"):
        validate_call_capacity(undersized, SimpleNamespace(dimensions=["modularity"]))


def test_source_navigation_continues_beyond_indexed_header():
    from server.agents.maintainability.modularity.architecture_boundary.execution import (
        BoundaryExecution,
    )

    source = SimpleNamespace(id="f", path="ai-service/config.js", line_count=90)
    reference = SimpleNamespace(id="e", file_id="f", kind="source", start_line=1, end_line=20)
    execution = SimpleNamespace(discovery=SimpleNamespace(ranked_files=lambda *args: [source]),
        unread_symbol_ranges=lambda *args, **kwargs: [], tools=SimpleNamespace(limits=SimpleNamespace(max_source_lines=20)))
    reads = BoundaryExecution.ranked_source_reads(execution, ["ai-service"], [], [reference])
    assert reads[0]["arguments"] == {"path": source.path, "start_line": 21, "end_line": 40}


def test_child_reservation_failure_explains_available_and_required():
    failure = {"code": "execution_budget_exhausted", "stage": "reserve_invocation",
        "summary": "No ejecutado: reserva insuficiente.",
        "resources": [{"resource": "calls", "available": 2, "required": 30}]}
    parent = SimpleNamespace(id="parent", agent_id="modularity", invocation_id="p", status="partial", model_dump=lambda **kwargs: {},
        details={"report": {"invocations": [{"assignment": {"invocation_id": "c", "investigator_id": "responsibility"},
            "status": "skipped", "error": "execution_budget_exhausted", "failure": failure}]}})
    child = next(issue for issue in execution_diagnostics([parent]) if issue.invocation_id == "c")
    assert child.termination_reason == "execution_budget_exhausted"
    assert "calls: disponible=2; requerido=30" in child.diagnostics
    assert child.explanation.startswith("No ejecutado")


def test_validation_failures_publish_host_cause_without_arbitrary_exception_values():
    safe = failure_from_exception(ExecutionValidationError("invalid_nested_evidence", "Evidencia no recopilada."), "validate_assessment")
    assert safe.code == "invalid_nested_evidence"
    assert safe.summary == "Evidencia no recopilada."
    unknown = failure_from_exception(ValueError("secret provider value"), "invoke_child")
    assert "secret" not in unknown.model_dump_json()
