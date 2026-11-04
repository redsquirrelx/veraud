"""Functional audit overrides must reach the existing shared runtime, not just its schema."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from config.agents.budgets import TokenBudgetPolicy
from config.agents.catalog import describe_agent_config
from server.agents.functional_adequacy import audit as functional_audit
from server.agents.functional_adequacy.agent import FunctionalAdequacyAgent
from server.agents.functional_adequacy.config import FunctionalAdequacyConfig
from server.agents.functional_adequacy.schemas import CodeEvidence
from server.app import audit_service
from server.app.audit_configuration import (
    FunctionalAuditOverrides,
    resolve_attribute_limits,
)
from server.app.audit_service import AuditService
from server.app.execution_config import ExecutionConfig
from server.blackboard.impls.memory import MemoryBlackboard
from server.config.token_budget import using_token_budget_policy
from server.main import app

pytest_plugins = ["test_audits"]


def test_functional_controls_derive_constraints_and_preserve_partial_quotas():
    runtime = FunctionalAdequacyConfig()
    schema = FunctionalAuditOverrides.model_json_schema()["properties"]
    owning = FunctionalAdequacyConfig.model_json_schema()["properties"]
    for name in ("timeout_seconds", "max_wall_time_seconds", "cancellation_grace_seconds",
            "provider_request_timeout_seconds", "max_provider_retries", "provider_rate_limits"):
        assert schema[name] == owning[name]
    assert not {"tools", "prompts", "max_tool_calls", "max_schema_retries",
        "max_schema_recovery_attempts", "max_output_tokens"} & schema.keys()
    user = describe_agent_config("functional_adequacy")
    assert set(user["config_schema"]["properties"]) == {"max_total_tokens", "timeout_seconds", "provider_rate_limits"}

    base = runtime.model_copy(update={"provider_rate_limits": runtime.provider_rate_limits.model_copy(
        update={"requests_per_minute": 33, "tokens_per_minute": 700000})})
    resolved = resolve_attribute_limits("functional_adequacy", {"functional_config": {
        "provider_rate_limits": {"requests_per_minute": None}, "max_provider_retries": 2}}, base=base)
    assert resolved.provider_rate_limits.requests_per_minute is None
    assert resolved.provider_rate_limits.tokens_per_minute == 700000
    assert resolved.max_provider_retries == 2
    assert resolved.embedding_model == runtime.embedding_model


def test_functional_configuration_endpoint_validates_transversal_controls():
    values = {"functional_config": {"timeout_seconds": 45, "max_wall_time_seconds": 90,
        "cancellation_grace_seconds": 1, "provider_request_timeout_seconds": 7, "max_provider_retries": 2,
        "provider_request_interval_seconds": 0.25, "provider_retry_backoff_seconds": 0.5,
        "provider_max_retry_wait_seconds": 10, "provider_recovery_budget_seconds": 12,
        "provider_rate_limits": {"requests_per_minute": None, "tokens_per_minute": 800000}}}
    with TestClient(app) as client:
        result = client.post("/api/audits/configuration/functional_adequacy/validate", json=values)
        assert result.status_code == 200, result.text
        assert result.json()["values"] == values
        for invalid in ({"timeout_seconds": 0}, {"max_wall_time_seconds": 0}, {"max_provider_retries": 9},
                {"provider_rate_limits": {"requests_per_minute": 0}}, {"tools": []}, {"api_key": "private"}):
            response = client.post("/api/audits/configuration/functional_adequacy/validate",
                json={"functional_config": invalid})
            assert response.status_code == 422


def _offline_retrieval(monkeypatch):
    def retrieve(self, state):
        fragment = state["input_data"].code_fragments[0]
        return {"candidates": {requirement.requirement_id: [CodeEvidence(fragment_id=fragment.fragment_id,
            file_path=fragment.file_path, similarity=0.9)] for requirement in state["input_data"].requirements}}

    monkeypatch.setattr(FunctionalAdequacyAgent, "_retrieve_candidates", retrieve)


def test_transversal_configuration_reaches_model_gateway_and_attribute_deadline(audit_environment, monkeypatch):
    _offline_retrieval(monkeypatch)
    model = audit_environment.model
    model.bind = lambda **kwargs: model
    model.ainvoke = AsyncMock(return_value=SimpleNamespace(content=json.dumps({
        "status": "cumple", "justification": "Returns a value."}), usage_metadata={"input_tokens": 20, "output_tokens": 5}))
    managed = []
    original = functional_audit.BudgetedModel

    class RecordingModel(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            managed.append(self)

    monkeypatch.setattr(functional_audit, "BudgetedModel", RecordingModel)
    options = {"functional_config": {"timeout_seconds": 47, "max_wall_time_seconds": 83,
        "cancellation_grace_seconds": 0.1, "provider_request_timeout_seconds": 11, "max_provider_retries": 2,
        "provider_request_interval_seconds": 0.01, "provider_retry_backoff_seconds": 0.1,
        "provider_max_retry_wait_seconds": 9, "provider_recovery_budget_seconds": 8,
        "provider_rate_limits": {"requests_per_minute": 123, "tokens_per_minute": 800000}},
        "agent_defaults": {"max_context_characters": 9000, "max_output_tokens": 512, "max_model_calls": 4}}

    async def run():
        service = AuditService(MemoryBlackboard())
        state = service.start(str(audit_environment.root), audit_service.MaintainabilityRequest(),
            ExecutionConfig(timeout_seconds=100), "functional_adequacy", attributes=["functional_adequacy"],
            functional_requirements=[{"requirement_id": "REQ-001", "description": "Return a value."}],
            attribute_options={"functional_adequacy": options})
        try:
            await service.wait(state.run_id)
            assert service.get(state.run_id).status == "completed"
        finally:
            await service.aclose()

    asyncio.run(run())
    runtime = managed[0]
    assert runtime.limits.timeout_seconds == 47, "Root transport timeout must not widen an explicit attribute cap"
    assert runtime.limits.max_wall_time_seconds == 83
    assert runtime.limits.cancellation_grace_seconds == 0.1
    assert runtime.limits.provider_rate_limits.requests_per_minute == 123
    assert runtime.limits.provider_rate_limits.tokens_per_minute == 800000
    assert runtime.gateway.request_timeout_seconds == 11
    assert runtime.gateway.pacer.max_retries == 2
    assert runtime.gateway.pacer.interval == 0.01
    assert runtime.gateway.pacer.backoff == 0.1
    assert runtime.gateway.max_retry_wait_seconds == 9
    assert runtime.gateway.recovery_budget_seconds == 8
    assert runtime.limits.max_context_characters == 9000
    assert runtime.limits.max_model_calls == 4
    assert model.ainvoke.await_args.kwargs["max_tokens"] == 512


@pytest.mark.parametrize("case,expected_calls", [("calls", 4), ("context", 0), ("local_tokens", 0),
    ("shared_tokens", 0), ("unlimited_tokens", 1)])
def test_configured_budgets_block_real_provider_calls(audit_environment, monkeypatch, case, expected_calls):
    from config.agents.budgets import TokenBudgetConfig

    _offline_retrieval(monkeypatch)
    model = audit_environment.model
    model.bind = lambda **kwargs: model
    model.ainvoke = AsyncMock(return_value=SimpleNamespace(content=json.dumps({
        "status": "cumple", "justification": "Returns a value."}), usage_metadata={"input_tokens": 20, "output_tokens": 5}))
    requirements = [{"requirement_id": f"REQ-{index}", "description": "x" * 5000 if case == "context" else "Return a value."}
        for index in range(5 if case == "calls" else 1)]
    options = {"agent_defaults": {"max_model_calls": 4, "max_context_characters": 4000,
        "max_total_tokens": 1000 if case in {"local_tokens", "unlimited_tokens"} else 100000}}

    async def run():
        service = AuditService(MemoryBlackboard())
        with using_token_budget_policy(TokenBudgetPolicy(unlimited_token_budget=case == "unlimited_tokens")):
            state = service.start(str(audit_environment.root), audit_service.MaintainabilityRequest(),
                ExecutionConfig(), "functional_adequacy", attributes=["functional_adequacy"],
                functional_requirements=requirements, attribute_options={"functional_adequacy": options},
                audit_budget=TokenBudgetConfig(max_total_tokens=1000) if case == "shared_tokens" else None)
            try:
                await service.wait(state.run_id)
                assessment = next(item for item in service.snapshot(state.run_id).assessments if item.agent_id == "functional_adequacy")
                output = assessment.details["functional_output"]
                assert output["results"][-1]["status"] == ("cumple" if case == "unlimited_tokens" else "evidencia_insuficiente")
                assert service.get(state.run_id).status == ("completed" if case == "unlimited_tokens" else "partial")
            finally:
                await service.aclose()

    asyncio.run(run())
    assert model.ainvoke.await_count == expected_calls


@pytest.mark.parametrize("requirements", [[], [{"requirement_id": "REQ-001", "description": "Return a value."}]])
def test_explicit_functional_deadline_stops_both_modes_without_changing_their_selection(audit_environment, monkeypatch, requirements):
    entered = []

    async def wait(self, prepared):
        entered.append(bool(prepared.requirements))
        await asyncio.sleep(10)

    monkeypatch.setattr(FunctionalAdequacyAgent, "run", wait)
    monkeypatch.setattr(audit_service, "default_model_configuration", dict)

    async def run():
        service = AuditService(MemoryBlackboard())
        state = service.start(str(audit_environment.root), audit_service.MaintainabilityRequest(),
            ExecutionConfig(timeout_seconds=10), "functional_adequacy", attributes=["functional_adequacy"],
            functional_requirements=requirements, attribute_options={"functional_adequacy": {"functional_config": {
                "timeout_seconds": 0.25, "max_wall_time_seconds": 0.5, "cancellation_grace_seconds": 0}}})
        try:
            await asyncio.wait_for(service.wait(state.run_id), timeout=3)
            assert service.get(state.run_id).status in {"failed", "partial"}
        finally:
            await service.aclose()

    asyncio.run(run())
    assert entered == [bool(requirements)]
    if not requirements:
        audit_environment.factory.assert_not_called()


@pytest.mark.parametrize("failure,retries,expected_calls", [("timeout", 1, 1), ("transient", 0, 1), ("transient", 1, 2)])
def test_provider_timeout_and_retry_overrides_bound_actual_attempts(audit_environment, monkeypatch, failure, retries, expected_calls):
    _offline_retrieval(monkeypatch)
    model = audit_environment.model
    model.bind = lambda **kwargs: model

    class Unavailable(RuntimeError):
        status_code = 503

    async def slow_provider(*args, **kwargs):
        if failure == "transient":
            raise Unavailable("Temporarily unavailable")
        await asyncio.sleep(10)

    model.ainvoke = AsyncMock(side_effect=slow_provider)

    async def run():
        service = AuditService(MemoryBlackboard())
        state = service.start(str(audit_environment.root), audit_service.MaintainabilityRequest(),
            ExecutionConfig(), "functional_adequacy", attributes=["functional_adequacy"],
            functional_requirements=[{"requirement_id": "REQ-001", "description": "Return a value."}],
            attribute_options={"functional_adequacy": {"functional_config": {
                "provider_request_timeout_seconds": 0.05, "max_provider_retries": retries,
                "provider_retry_backoff_seconds": 0}}})
        try:
            await asyncio.wait_for(service.wait(state.run_id), timeout=3)
            assert service.get(state.run_id).status == "partial"
        finally:
            await service.aclose()

    asyncio.run(run())
    assert model.ainvoke.await_count == expected_calls


def test_null_functional_patch_preserves_transport_timeout_and_exploratory_mode(audit_environment, monkeypatch):
    observed = []
    original = FunctionalAdequacyAgent._prepare

    async def prepare(self, state):
        observed.append(self.config.timeout_seconds)
        return await original(self, state)

    monkeypatch.setattr(FunctionalAdequacyAgent, "_prepare", prepare)

    async def run():
        service = AuditService(MemoryBlackboard())
        state = service.start(str(audit_environment.root), audit_service.MaintainabilityRequest(),
            ExecutionConfig(timeout_seconds=12), "functional_adequacy", attributes=["functional_adequacy"],
            attribute_options={"functional_adequacy": {"functional_config": None}})
        try:
            await service.wait(state.run_id)
            assessment = next(item for item in service.snapshot(state.run_id).assessments if item.agent_id == "functional_adequacy")
            assert assessment.details["functional_output"]["audit_mode"] == "exploratory"
        finally:
            await service.aclose()

    asyncio.run(run())
    assert observed == [12]
    audit_environment.factory.assert_not_called()
