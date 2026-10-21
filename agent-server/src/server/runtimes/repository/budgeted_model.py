"""Adapt a managed chat model to the generate protocol with shared runtime limits."""

from langchain_core.messages import HumanMessage

from ...config.token_budget import token_budget_exceeded
from ...infrastructure.llm.chat import prepare_chat_model
from ..investigation.provider import ProviderPacer
from .model_runtime import ModelGateway
from .timing import within_deadline


class BudgetedModel:
    def __init__(self, model, limits, tokens, timing):
        self.model, self.options, self.output_limit = prepare_chat_model(model,
            max_output_tokens=limits.max_output_tokens, request_timeout_seconds=limits.provider_request_timeout_seconds)
        self.limits, self.tokens, self.timing = limits, tokens, timing
        self.pacer = ProviderPacer(rate_limits=limits.provider_rate_limits, provider_config=limits)
        self.reservation = None
        self.attempts = 0
        self.gateway = ModelGateway(self, provider_config=limits, remaining_seconds=lambda: timing.active_remaining)
        self.gateway.request_guard = self.guard

    def guard(self, prompt, attempt):
        reserve = max(1, len(prompt)) + self.output_limit
        if len(prompt) > self.limits.max_context_characters:
            raise ValueError("context_budget_exhausted")
        if self.attempts >= self.limits.max_model_calls:
            raise ValueError("model_call_budget_exhausted")
        if token_budget_exceeded(self.tokens.used + reserve, self.limits.max_total_tokens):
            raise ValueError("local_token_budget_exhausted")
        self.reservation = self.tokens.reserve(reserve)
        if self.reservation is None:
            raise ValueError("shared_token_budget_exhausted")
        self.attempts += 1

    async def generate(self, prompt):
        """Raw delegate used by ModelGateway; callers use call() for pacing/retries."""
        with self.timing.quota_wait() as waiting:
            quota = await within_deadline(self.pacer.acquire(max(1, len(prompt)) + self.output_limit,
                on_wait=lambda seconds, reasons: waiting.update(reason="+".join(reasons),
                    until=self.timing.clock() + seconds, source="local_rolling_window")), self.timing)
        response = await self.model.ainvoke([HumanMessage(content=prompt)], **self.options)
        usage = getattr(response, "usage_metadata", None)
        if isinstance(usage, dict) and isinstance(usage.get("input_tokens"), int) and isinstance(usage.get("output_tokens"), int):
            actual = usage["input_tokens"] + usage["output_tokens"]
            self.reservation.settle(actual)
            self.pacer.settle(quota, actual)
        return response

    async def call(self, prompt):
        return await self.gateway(prompt)
