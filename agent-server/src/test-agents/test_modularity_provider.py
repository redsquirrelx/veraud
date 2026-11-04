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
from server.agents.maintainability.modularity.coordinator import (
    ModularityConfig,
    ModularityRequest,
)
from server.agents.maintainability.modularity.coordinator.agent import (
    ModularityExecution,
)
from server.agents.maintainability.modularity.coordinator.schemas import SynthesisDraft
from server.agents.maintainability.modularity.dependency_impact import (
    DependencyImpactAgent,
)
from server.agents.maintainability.modularity.responsibility import ResponsibilityAgent
from server.agents.maintainability.reusability.component_adaptability import (
    ComponentAdaptabilityAgent,
)
from server.agents.maintainability.reusability.reuse_opportunity import (
    ReuseOpportunityAgent,
)
from server.contracts.legacy_schemes.investigator import BoundaryReview
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
    config = BoundaryConfig(**({"provider_retry_backoff_seconds": 0} | updates))
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
    unavailable = errors.ServerError(503, response_json={"error": {"code": 503, "message": "Unavailable"}})
    run, model = execution(repo, [unavailable] * 4, max_provider_retries=1)
    result = asyncio.run(run.call("review_findings", run.initial_state(), Review))
    assert result is None and run.stop == "provider_recovery_exhausted" and run.retryable_failure
    assert run.calls == len(model.history) == 2


@pytest.mark.parametrize(("retries", "budget", "sleeps_expected", "reason"), [
    (4, 60, [2, 4, 8, 16], "provider_recovery_exhausted"),
    (4, 3, [2], "provider_recovery_budget"),
    (0, 0, [], "provider_recovery_exhausted"),
])
def test_failed_planning_reports_the_actual_retry_blocker_and_skips_unstarted_stages(
        repo, retries, budget, sleeps_expected, reason):
    unavailable = errors.ServerError(503, response_json={"error": {"code": 503, "message": "Unavailable"}})
    run, model = execution(repo, [unavailable] * 5, max_provider_retries=retries,
        provider_retry_backoff_seconds=2, provider_recovery_budget_seconds=budget)
    sleeps, visited = [], []

    async def fast_sleep(seconds):
        sleeps.append(seconds)

    run.provider_pacer.sleep = fast_sleep

    async def execute():
        result = None
        async for update in run.graph.astream(run.initial_state(), stream_mode="updates"):
            visited.extend(update)
            if "finalize" in update:
                result = update["finalize"]["result"]
        return result

    result = asyncio.run(execute())
    assert visited == ["plan_investigation", "finalize"]
    assert sleeps == sleeps_expected and run.recovery_wait_seconds == sum(sleeps_expected)
    assert result.termination_reason == reason
    assert result.model_calls == len(model.history) == len(sleeps_expected) + 1
    assert result.plan is None and result.iterations == result.tool_calls == 0
    assert result.findings == result.hypotheses == result.evidence == []
    assert result.critical_review is None and result.evaluation_evidence_status == "not_evaluated"
    assert result.accounted_tokens == result.estimated_tokens > 0
    stage, = result.deferred_stages
    assert stage.node == "plan_investigation" and stage.reason == reason
    assert stage.attempts == result.model_calls and stage.http_status == 503
    assert any("were not started" in item for item in result.missing_information)
    assert not any("A valid evidence evaluation could not" in item for item in result.missing_information)


@pytest.mark.parametrize("agent_type", [ResponsibilityAgent, DependencyImpactAgent,
    ComponentAdaptabilityAgent, ReuseOpportunityAgent])
def test_shared_and_specialized_graphs_finalize_directly_when_planning_fails(repo, agent_type):
    model = ScriptedModel([RuntimeError("Planning provider unavailable")])
    agent = agent_type(model)
    run = agent.execution_type(model, agent.config, toolset(repo), agent.request_type())
    visited = []
    closing_node = ("limited_finalize" if agent_type in {ComponentAdaptabilityAgent, ReuseOpportunityAgent}
        else "finalize")

    async def execute():
        result = None
        async for update in run.graph.astream(run.initial_state(), stream_mode="updates"):
            visited.extend(update)
            if closing_node in update:
                result = update[closing_node]["result"]
        return result

    result = asyncio.run(execute())
    assert visited == ["plan_investigation", closing_node]
    assert result.plan is None and result.iterations == result.tool_calls == 0
    assert result.model_calls == len(model.history) == 1
    assert result.termination_reason == "model_or_schema_error"


@pytest.mark.parametrize("blocker", ["token", "call"])
def test_first_gateway_timeout_reports_the_budget_blocking_retry(repo, blocker):
    def timeout(messages):
        # Reproduce a closing request that fits once but cannot be retried.
        if blocker == "token":
            run.token_limit = run.tokens + 1
        else:
            run.call_limit = run.calls
        return errors.ServerError(504, response_json={"error": {"code": 504, "message": "Gateway timeout"}})

    run, model = execution(repo, [timeout])
    result = asyncio.run(run.call("review_findings", run.initial_state(), Review))
    assert result is None and len(model.history) == run.calls == 1
    assert run.stop == f"provider_retry_{blocker}_limit"
    assert run.deferred_stages[0].reason == run.stop
    assert run.deferred_stages[0].http_status == 504
    assert run.deferred_stages[0].attempts == 1
    assert run.recovery_wait_seconds == 0


def test_one_slow_provider_request_is_bounded_and_visible_without_restarting(repo):
    run, model = execution(repo, [], provider_request_timeout_seconds=0.03, cancellation_grace_seconds=0.01)
    entered = asyncio.Event()
    calls = []

    async def slow(*args, **kwargs):
        calls.append(1)
        entered.set()
        await asyncio.Event().wait()

    model.ainvoke = slow
    run.tools.execute("get_source_excerpt", {"path": "main.py", "start_line": 1, "end_line": 1}, tool_call_id="retained")

    async def execute():
        task = asyncio.create_task(run.call("review_findings", run.initial_state(), Review))
        await entered.wait()
        activity = run.timing.activity()
        assert any(item["stage"] == "review_findings:provider_request" and item["status"] == "running" for item in activity)
        done, _ = await asyncio.wait({task}, timeout=0.4)
        assert done
        assert await task is None

    asyncio.run(execute())
    assert run.stop == "provider_request_timeout"
    assert len(calls) == run.calls == 1
    assert run.references()[0].tool_call_id == "retained"
    assert run.deferred_stages[0].reason == "provider_request_timeout"
    assert run.timing.remaining > 0 and not run.timing.activity()


@pytest.mark.parametrize(("delay", "limit"), [("44378s", 120), ("11s", 10)])
def test_provider_long_wait_terminates_without_sleep_or_new_requests(repo, delay, limit):
    run, model = execution(repo, [rate_limit(delay)], provider_max_retry_wait_seconds=limit)

    async def forbidden_sleep(seconds):
        pytest.fail("A rejected provider delay must not enter quota recovery")

    run.provider_pacer.sleep = forbidden_sleep
    result = asyncio.run(run.call("review_findings", run.initial_state(), Review))
    assert result is None and run.stop == "provider_retry_wait_limit"
    assert not run.retryable_failure
    assert run.calls == len(model.history) == 1
    assert not run.timing.waiting()
    assert any(f"max_wait_seconds={limit}" in issue and "resultados parciales conservados" in issue for issue in run.issues)
    assert "PRIVATE_SOURCE_AND_API_KEY" not in str(run.issues)


def test_long_quota_wait_exits_investigator_graph_with_explicit_limitation(repo):
    model = ScriptedModel([rate_limit("44378s")])
    agent = ArchitectureBoundaryAgent(model, BoundaryConfig())
    result = asyncio.run(agent.run(toolset(repo), agent.request_type()))
    assert result.termination_reason == "provider_retry_wait_limit"
    assert result.model_calls == len(model.history) == 1
    assert not result.findings
    assert "provider_retry_wait_limit" in str(result)


@pytest.mark.parametrize("delay", ["1s", "37020s"])
def test_daily_quota_is_deferred_without_retry_and_preserves_evidence(repo, delay):
    from server.infrastructure.llm.retry import retryable
    from server.runtimes.coordination.synthesis import terminal_provider_blocker

    cause = errors.ClientError(429, response_json={"error": {"code": 429, "details": [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{
            "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay},
    ]}})
    wrapped = GoogleRateLimitError("PRIVATE_PROVIDER_DETAILS")
    wrapped.__cause__ = cause
    assert not retryable(cause) and not retryable(wrapped)
    model = ScriptedModel([wrapped])
    agent = ArchitectureBoundaryAgent(model, BoundaryConfig())
    child = toolset(repo)
    run = agent.execution_type(model, agent.config, child, agent.request_type())
    child.execute("get_source_excerpt", {"path": "main.py", "start_line": 1, "end_line": 1}, tool_call_id="before-outage")
    result = asyncio.run(run.graph.ainvoke(run.initial_state()))["result"]
    assert result.termination_reason == "provider_daily_quota_exhausted"
    assert result.model_calls == len(model.history) == 1
    assert result.evidence and result.evidence[0].tool_call_id == "before-outage"
    assert result.deferred_stages[0].retry_after_seconds == float(delay[:-1])
    assert terminal_provider_blocker(result)
    assert "PRIVATE_PROVIDER_DETAILS" not in str(result)


def test_retry_cannot_consume_reserved_review_calls(repo):
    run, model = execution(repo, [rate_limit("0s")] * 4, max_model_calls=4)
    result = asyncio.run(run.call("plan_investigation", run.initial_state(), Review))
    assert result is None
    assert run.calls == len(model.history) == 1  # three cognitive calls remain reserved


def test_explicit_wall_deadline_can_cancel_quota_recovery(repo):
    run, model = execution(repo, [rate_limit("60s")], timeout_seconds=2)
    run.timing.wall_deadline = monotonic() + 0.05
    result = asyncio.run(run.call("review_findings", run.initial_state(), Review))
    assert result is None and run.calls == len(model.history) == 1
    assert run.stop == "time_limit" and run.provider_pacer.next_allowed <= monotonic()


def test_provider_recovery_is_scoped_to_the_failed_invocation(repo):
    async def execute():
        first, _ = execution(repo, [rate_limit(), {"findings": [], "limitations": []}], max_provider_retries=0)
        second, model = execution(repo, [{"findings": [], "limitations": []}])
        second.provider_pacer = first.provider_pacer
        started = monotonic()
        first_result, result = await asyncio.gather(first.call("review_findings", first.initial_state(), Review),
            second.call("review_findings", second.initial_state(), Review))
        assert first_result is not None and result is not None and len(model.history) == 1
        assert monotonic() - started >= 0.005
    asyncio.run(execute())


def test_long_retry_after_does_not_block_agents_whose_requests_succeed(repo):
    async def execute():
        first, first_model = execution(repo, [rate_limit("30s"), {"findings": [], "limitations": []}], max_provider_retries=0)
        second, model = execution(repo, [{"findings": [], "limitations": []}])
        second.provider_pacer = first.provider_pacer
        now, waiting, release = [0.0], asyncio.Event(), asyncio.Event()

        async def recover(delay):
            target = now[0] + delay
            waiting.set()
            await release.wait()
            now[0] = max(now[0], target)

        first.provider_pacer.clock = lambda: now[0]
        first.provider_pacer.sleep = recover
        first_task = asyncio.create_task(first.call("review_findings", first.initial_state(), Review))
        second_task = None
        try:
            await asyncio.wait_for(waiting.wait(), 1)
            second_task = asyncio.create_task(second.call("review_findings", second.initial_state(), Review))
            second_result = await asyncio.wait_for(second_task, 0.2)
            assert second_result is not None and not first_task.done()
            assert len(model.history) == len(first_model.history) == 1
            assert first.timing.waiting()[0]["source"] == "google.rpc.RetryInfo.retryDelay"
            assert first.timing.waiting()[0]["reason"] == "provider_retry_after"
            assert first.provider_pacer.next_allowed <= first.provider_pacer.clock()
            release.set()
            results = await asyncio.wait_for(asyncio.gather(first_task, second_task), 1)
            assert all(result is not None for result in results)
            assert not first.stop and not second.stop
            assert first.calls == 2 and second.calls == 1 and now[0] >= 30
        finally:
            first_task.cancel()
            if second_task is not None:
                second_task.cancel()
            await asyncio.gather(*(task for task in (first_task, second_task) if task is not None), return_exceptions=True)

    asyncio.run(execute())


def test_four_429_responses_do_not_block_two_successful_agents_next_steps(repo):
    async def execute():
        review = {"findings": [], "limitations": []}
        workers = [execution(repo, [rate_limit("30s"), review], max_provider_retries=0) for _ in range(4)]
        successful = [execution(repo, [review, review]) for _ in range(2)]
        shared = workers[0][0].provider_pacer
        now, release, all_waiting = [0.0], asyncio.Event(), asyncio.Event()
        waiting = 0

        async def recover(delay):
            nonlocal waiting
            target = now[0] + delay
            waiting += 1
            if waiting == 4:
                all_waiting.set()
            await release.wait()
            now[0] = max(now[0], target)

        shared.clock, shared.sleep = lambda: now[0], recover
        for run, _ in workers + successful:
            run.provider_pacer = shared

        async def advance(run):
            first = await run.call("review_findings", run.initial_state(), Review)
            second = await run.call("review_findings", run.initial_state(), Review)
            assert first is not None and second is not None

        pending = [asyncio.create_task(run.call("review_findings", run.initial_state(), Review)) for run, _ in workers]
        advancing = [asyncio.create_task(advance(run)) for run, _ in successful]
        try:
            await asyncio.wait_for(all_waiting.wait(), 1)
            await asyncio.wait_for(asyncio.gather(*advancing), 1)
            assert all(not task.done() for task in pending)
            assert all(len(model.history) == 2 for _, model in successful)
            release.set()
            results = await asyncio.wait_for(asyncio.gather(*pending), 1)
            assert all(result is not None for result in results)
            assert all(not run.stop for run, _ in workers + successful)
        finally:
            for task in pending + advancing:
                task.cancel()
            await asyncio.gather(*pending, *advancing, return_exceptions=True)

    asyncio.run(execute())


def test_recovery_wait_allowance_is_cumulative_across_calls_and_never_sleeps_past_it(repo):
    unavailable = errors.ServerError(503, response_json={"error": {"code": 503, "message": "Unavailable"}})
    review = {"findings": [], "limitations": []}
    run, model = execution(repo, [unavailable, review, unavailable],
        provider_retry_backoff_seconds=2, provider_recovery_budget_seconds=3)
    sleeps = []

    async def fast_sleep(seconds):
        sleeps.append(seconds)

    run.provider_pacer.sleep = fast_sleep

    async def execute():
        first = await run.call("review_findings", run.initial_state(), Review)
        assert first is not None
        second = await run.call("review_findings", run.initial_state(), Review)
        assert second is None

    asyncio.run(execute())
    assert sleeps == [2]
    assert run.recovery_wait_seconds == 2
    assert run.stop == "provider_recovery_budget"
    assert run.deferred_stages[0].node == "review_findings"
    assert run.calls == len(model.history) == 3


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


def test_invalid_request_diagnostic_keeps_known_fields_and_discards_provider_values():
    error = GoogleInvalidRequestError("PRIVATE_SOURCE_AND_API_KEY")
    error.__cause__ = errors.ClientError(400, response_json={"error": {"code": 400,
        "status": "INVALID_ARGUMENT", "message": "Invalid request: PRIVATE_SOURCE_AND_API_KEY",
        "details": [{"@type": "type.googleapis.com/google.rpc.BadRequest", "fieldViolations": [
            {"field": "generationConfig.responseJsonSchema.properties.PRIVATE_FIELD", "description": "PRIVATE_VALUE"},
            {"field": "generationConfig.maxOutputTokens", "description": "PRIVATE_VALUE"},
            {"field": "PRIVATE_FIELD", "description": "PRIVATE_VALUE"},
        ]}]}})
    diagnostic = provider_diagnostic(error)
    assert "http_status=400" in diagnostic and "invalid_argument" in diagnostic
    assert "request_field=response_json_schema" in diagnostic
    assert "request_field=max_output_tokens" in diagnostic
    assert "PRIVATE" not in diagnostic


def test_request_diagnostic_reads_http_response_body_without_leaking_provider_values():
    from types import SimpleNamespace

    error = RuntimeError("PRIVATE_MESSAGE")
    error.response = SimpleNamespace(status_code=400, json=lambda: {"error": {
        "message": "PRIVATE_MESSAGE", "details": [{"@type": "type.googleapis.com/google.rpc.BadRequest",
            "fieldViolations": [{"field": "generationConfig.thinkingConfig.PRIVATE_FIELD", "description": "PRIVATE_VALUE"}]}]}})
    diagnostic = provider_diagnostic(error)
    assert "http_status=400" in diagnostic
    assert "request_field=thinking_config" in diagnostic
    assert "PRIVATE" not in diagnostic


def test_boundary_google_lean_schema_still_enforces_local_bounds(repo, monkeypatch):
    model = ChatGoogleGenerativeAI(model="gemini-3.1-flash-lite", api_key="offline-test-key", max_retries=0)
    requests = []
    async def generate_content(**kwargs):
        requests.append(kwargs)
        schema = kwargs["config"].response_json_schema
        assert schema["title"] == "BoundaryReview" and "maxItems" not in json.dumps(schema)
        invalid = {"findings": [{"finding_id": "f", "status": "insufficient_evidence", "rationale": "Missing scope",
            "severity": "info", "confidence": 0, "unverified_claims": ["Missing implementation"] * 21}]}
        value = invalid if len(requests) == 1 else {"findings": [], "limitations": []}
        return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(
            role="model", parts=[types.Part(text=json.dumps(value))]), finish_reason="STOP")],
            usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=100, candidates_token_count=30, total_token_count=130))

    monkeypatch.setattr(model.async_client.models, "generate_content", generate_content)
    agent = ArchitectureBoundaryAgent(model)
    run = agent.execution_type(model, agent.config, toolset(repo), agent.request_type())
    value = asyncio.run(run.call("review_findings", run.initial_state(), BoundaryReview))
    assert value is not None and not value.findings and not run.stop
    assert len(requests) == run.calls == 2 and run.tokens == 260
    assert any("unverified_claims: too_long" in issue for issue in run.issues)


@pytest.mark.parametrize("agent_type", [DependencyImpactAgent, ResponsibilityAgent])
def test_all_investigators_send_lean_native_schemas_and_exact_review_candidate_ids(repo, monkeypatch, agent_type):
    model = ChatGoogleGenerativeAI(model="gemini-3.5-flash-lite", api_key="offline-test-key", max_retries=0)
    requests = []

    async def generate_content(**kwargs):
        requests.append(kwargs)
        schema = kwargs["config"].response_json_schema
        assert "maxItems" not in json.dumps(schema)
        assert "maxLength" not in json.dumps(schema)
        assert "Authoritative review candidate IDs" in str(kwargs["contents"])
        return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(
            role="model", parts=[types.Part(text=json.dumps({"findings": [], "limitations": []}))]), finish_reason="STOP")])

    monkeypatch.setattr(model.async_client.models, "generate_content", generate_content)
    agent = agent_type(model)
    run = agent.execution_type(model, agent.config, toolset(repo), agent.request_type())
    result = asyncio.run(run.call("review_findings", run.initial_state(), Review))
    assert result is not None and result.findings == []
    assert len(requests) == 1


def test_empty_synthesis_groups_do_not_consume_correction_calls_or_invent_references(repo):
    model = ScriptedModel([{"summary": "No supported groups", "groups": [{"finding_refs": []}]}])
    agent = type("Agent", (), {"model": model, "config": ModularityConfig()})()
    run = ModularityExecution(agent, toolset(repo), ModularityRequest())
    result = asyncio.run(run.synth.call("synthesize_findings", {"messages": [], "compact_context": {}}, SynthesisDraft))
    assert result is not None and result.groups == []
    assert run.synth.calls == 1
    assert any("empty finding groups" in issue for issue in run.synth.issues)


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
    run = ModularityExecution(agent, toolset(repo), ModularityRequest())
    result = asyncio.run(run.synth.call("synthesize_findings", {"messages": [], "compact_context": {}}, SynthesisDraft))
    assert result.summary == "Scoped synthesis"
    assert len(requests) == run.synth.calls == 1
    assert run.synth.tokens == 130


def test_synthesis_can_recover_on_a_later_round(repo):
    from test_architecture_boundary import NativeStructuredModel

    unavailable = errors.ServerError(503, response_json={"error": {"code": 503, "message": "Unavailable"}})
    model = NativeStructuredModel([unavailable, {"summary": "Recovered synthesis"}])
    config = ModularityConfig(max_provider_retries=0, provider_retry_backoff_seconds=0)
    agent = type("Agent", (), {"model": model, "config": config})()
    run = ModularityExecution(agent, toolset(repo), ModularityRequest())
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
