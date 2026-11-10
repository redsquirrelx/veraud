"""Provider retries consume investigation budget and stop honestly."""

import asyncio

import httpx
from test_architecture_boundary_planning import tools_for

from server.agents.maintainability.v2.reusability.abstraction_doc_driven import (
    AbstractionAgent,
    AbstractionConfig,
    AbstractionRequest,
)


class UnavailableModel:
    def __init__(self):
        self.calls = 0

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages, **kwargs):
        self.calls += 1
        request = httpx.Request("POST", "https://example.test/x")
        response = httpx.Response(503, request=request)
        raise httpx.HTTPStatusError("unavailable", request=request, response=response)


def test_transient_503_is_not_ignored_and_attempt_budget_is_respected(tmp_path):
    tools = tools_for(tmp_path, {
        "src/llm/provider.py": (
            "from typing import Protocol\n\nclass LlmProvider(Protocol):\n"
            "    def complete(self, prompt): ...\n"),
        "src/llm/gemini.py": "class GeminiProvider(LlmProvider):\n    def complete(self, prompt): return 'x'\n",
    })
    model = UnavailableModel()
    config = AbstractionConfig(provider_retry_backoff_seconds=0,
        provider_max_retry_wait_seconds=0,
        provider_recovery_budget_seconds=0)

    result = asyncio.run(AbstractionAgent(model, config).run(tools, AbstractionRequest()))

    assert result.termination_reason in {"provider_recovery_exhausted", "provider_retry_call_limit",
        "provider_recovery_budget", "provider_retry_wait_limit", "provider_retry_token_limit"}
    assert model.calls <= config.max_provider_retries + 1
    assert model.calls >= 1
