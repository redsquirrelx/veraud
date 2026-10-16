"""Offline: uv run pytest src/test-agents/test_modularity_provider.py -q.

Real Google adapter/exception types, mocked transport; no credentials or paid calls.
"""

import asyncio
import json
from time import monotonic

import pytest
from google.genai import errors, types
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_google_genai.chat_models import (
    GoogleInvalidRequestError,
    GoogleRateLimitError,
)
from pydantic import ValidationError
from test_architecture_boundary import ScriptedModel, toolset
from test_modularity_e2e import assert_live_success

from server.agents.maintainability.modularity.architecture_boundary import (
    ArchitectureBoundaryAgent,
    BoundaryConfig,
)
from server.agents.maintainability.modularity.coordinator import ModularityConfig, ModularityRequest
from server.agents.maintainability.modularity.coordinator.agent import _Execution
from server.agents.maintainability.modularity.coordinator.schemas import SynthesisDraft
from server.runtimes.investigation.provider import (
    lean_schema,
    provider_diagnostic,
    provider_status,
    transient,
)
from server.runtimes.investigation.schemas import Review


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    (root / "main.py").write_text("value = 1\n", encoding="utf-8")
    return root


def rate_limit(delay="0.01s"):
    cause = errors.ClientError(429, response_json={"error": {"code": 429,
        "status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded: PRIVATE_SOURCE_AND_API_KEY",
        "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay}]}})
    error = GoogleRateLimitError("PRIVATE_SOURCE_AND_API_KEY")
    error.__cause__ = cause
    return error


def execution(root, responses, **updates):
    model = ScriptedModel(responses)
    config = BoundaryConfig(provider_retry_backoff_seconds=0, **updates)
    agent = ArchitectureBoundaryAgent(model, config)
    return agent.execution_type(model, config, toolset(root), agent.request_type()), model


def test_wrapped_google_rate_limit_retries_and_accounts_attempts(repo):
    run, model = execution(repo, [rate_limit(), {"findings": [], "limitations": []}])
    started = monotonic()
    result = asyncio.run(run.call("review_findings", run.initial_state(), Review))
    assert result is not None and not run.stop
    assert run.calls == len(model.history) == 2
    assert run.estimates == run.tokens > 0  # both unknown-usage attempts stay charged
    assert monotonic() - started >= 0.01
    assert any("http_status=429" in issue and "retry_after_seconds=0.01" in issue for issue in run.issues)
    assert "PRIVATE_SOURCE_AND_API_KEY" not in str(run.issues)


def test_retry_limit_exhaustion_is_bounded(repo):
    run, model = execution(repo, [rate_limit("0s")] * 4, max_provider_retries=1)
    result = asyncio.run(run.call("review_findings", run.initial_state(), Review))
    assert result is None and run.stop == "model_or_schema_error" and run.retryable_failure
    assert run.calls == len(model.history) == 2


def test_retry_cannot_consume_reserved_review_calls(repo):
    run, model = execution(repo, [rate_limit("0s")] * 4, max_model_calls=4)
    result = asyncio.run(run.call("plan_investigation", run.initial_state(), Review))
    assert result is None
    assert run.calls == len(model.history) == 1  # three cognitive calls remain reserved


def test_retry_after_beyond_deadline_does_not_wait_or_retry(repo):
    run, model = execution(repo, [rate_limit("600s")], timeout_seconds=2)
    result = asyncio.run(run.call("review_findings", run.initial_state(), Review))
    assert result is None and run.calls == len(model.history) == 1
    assert run.provider_pacer.next_allowed - monotonic() > 590


def test_cooldown_is_shared_between_investigators(repo):
    async def execute():
        first, _ = execution(repo, [rate_limit()], max_provider_retries=0)
        second, model = execution(repo, [{"findings": [], "limitations": []}])
        second.provider_pacer = first.provider_pacer
        await first.call("review_findings", first.initial_state(), Review)
        started = monotonic()
        result = await second.call("review_findings", second.initial_state(), Review)
        assert result is not None and len(model.history) == 1
        assert monotonic() - started >= 0.005
    asyncio.run(execute())


def test_provider_retry_cannot_exceed_token_budget(repo):
    def fail(messages):
        run.token_limit = run.tokens  # first attempted request consumed all remaining reservation
        return rate_limit("0s")
    run, model = execution(repo, [fail])
    result = asyncio.run(run.call("review_findings", run.initial_state(), Review))
    assert result is None and run.calls == len(model.history) == 1


def test_permanent_invalid_request_is_not_retried_or_leaked(repo):
    error = GoogleInvalidRequestError("PRIVATE_SOURCE_AND_API_KEY")
    error.__cause__ = errors.ClientError(400, response_json={"error": {"code": 400,
        "status": "INVALID_ARGUMENT", "message": "Response schema has too many states; PRIVATE_SOURCE_AND_API_KEY"}})
    run, model = execution(repo, [error])
    result = asyncio.run(run.call("review_findings", run.initial_state(), Review))
    assert result is None and not run.retryable_failure
    assert run.calls == len(model.history) == 1
    assert "http_status=400" in run.issues[0] and "schema_complexity" in run.issues[0]
    assert "PRIVATE_SOURCE_AND_API_KEY" not in run.issues[0]


def test_shared_pacing_wait_is_cancellable_and_does_not_charge_provider(repo):
    async def execute():
        run, model = execution(repo, [])
        run.provider_pacer.next_allowed = monotonic() + 10
        task = asyncio.create_task(run.call("review_findings", run.initial_state(), Review))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert run.calls == 0 and not model.history
    asyncio.run(execute())


def test_lean_schema_retains_local_constraints():
    schema = lean_schema(SynthesisDraft)
    assert "maxItems" not in json.dumps(schema) and "maxLength" not in json.dumps(schema)
    assert schema["properties"]["summary"]["type"] == "string"
    assert "summary" in schema["required"]
    assert schema["$defs"]["ProposedGap"]["properties"]["investigator_id"]["enum"]
    with pytest.raises(ValidationError):
        SynthesisDraft.model_validate({"summary": "x" * 3001})


def test_synthesis_google_real_adapter_receives_lean_schema(repo, monkeypatch):
    model = ChatGoogleGenerativeAI(model="gemini-3.5-flash-lite", api_key="offline-test-key", max_retries=0)
    requests = []
    async def generate_content(**kwargs):
        schema = kwargs["config"].response_json_schema
        requests.append(kwargs)
        # Model the documented native-schema complexity rejection, not provider I/O.
        assert "maxItems" not in json.dumps(schema)
        assert "maxLength" not in json.dumps(schema)
        return types.GenerateContentResponse(candidates=[types.Candidate(
            content=types.Content(role="model", parts=[types.Part(text=json.dumps({"summary": "Scoped synthesis"}))]),
            finish_reason="STOP")], usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=100, candidates_token_count=30, total_token_count=130))
    monkeypatch.setattr(model.async_client.models, "generate_content", generate_content)
    agent = type("Agent", (), {"model": model, "config": ModularityConfig()})()
    run = _Execution(agent, toolset(repo), ModularityRequest())
    result = asyncio.run(run.synth.call("synthesize_findings", {"messages": [], "compact_context": {}}, SynthesisDraft))
    assert result.summary == "Scoped synthesis"
    assert len(requests) == run.synth.calls == 1
    assert run.synth.tokens == 130


def test_synthesis_can_recover_on_a_later_round(repo):
    from test_architecture_boundary import NativeStructuredModel

    model = NativeStructuredModel([rate_limit("0s"), {"summary": "Recovered synthesis"}])
    config = ModularityConfig(max_provider_retries=0, provider_retry_backoff_seconds=0)
    agent = type("Agent", (), {"model": model, "config": config})()
    run = _Execution(agent, toolset(repo), ModularityRequest())
    state = run.initial_state()
    state.update(run.plan_assessment(state))
    first = asyncio.run(run.synthesize_findings(state))
    assert any(g.kind == "synthesis_failure" for g in first["material_gaps"])
    state.update(first)
    second = asyncio.run(run.synthesize_findings(state))
    assert not any(g.kind == "synthesis_failure" for g in second["material_gaps"])
    assert "synthesis-failure" in second["resolved_gap_ids"]
    assert run.synth.calls == 2 and run.spent.model_calls == 2


def test_provider_classification_does_not_guess_from_generic_errors():
    error = RuntimeError("PRIVATE_SOURCE_AND_API_KEY")
    assert provider_status(error) is None and not transient(error)
    assert provider_diagnostic(error) == ""


def test_live_success_rejects_tool_activity_without_complete_evaluation():
    # Faithful shape of the failed live run: plans and tool evidence, no completed investigator.
    from types import SimpleNamespace

    assessment = SimpleNamespace(invocations=[SimpleNamespace(status="partial", result=object(), evidence=[object()])], material_gaps=[])
    with pytest.raises(AssertionError, match="Ningun investigador"):
        assert_live_success(assessment)


def test_live_success_rejects_failed_synthesis_despite_completed_investigator():
    from types import SimpleNamespace

    assessment = SimpleNamespace(invocations=[SimpleNamespace(status="completed",
        result=SimpleNamespace(plan=object()), evidence=[object()])],
        material_gaps=[SimpleNamespace(kind="synthesis_failure")])
    with pytest.raises(AssertionError, match="La sintesis fallo"):
        assert_live_success(assessment)
