"""Adapt a managed chat model to the generate protocol with shared runtime limits."""

from contextvars import ContextVar

from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from ...agent_services.budgeting.policy import budgets_enabled, token_budget_exceeded
from ...agent_services.budgeting.timing import within_deadline
from ...infrastructure.llm.chat import prepare_chat_model
from ..investigation.provider import lean_schema, model_pacer
from ..investigation.structured import finish_diagnostic
from .model_runtime import ModelGateway


class BudgetedModel:
    def __init__(self, model, limits, tokens, timing):
        self.model, self.options, self.output_limit = prepare_chat_model(
            model,
            max_output_tokens=limits.max_output_tokens,
            request_timeout_seconds=limits.provider_request_timeout_seconds,
        )
        self.limits, self.tokens, self.timing = limits, tokens, timing
        self.pacer = model_pacer(
            model, rate_limits=limits.provider_rate_limits, provider_config=limits
        )
        self.reservation = None
        self.attempts = 0
        self._request_model = ContextVar("budgeted_request_model", default=None)
        self.gateway = ModelGateway(
            self,
            provider_config=limits,
            remaining_seconds=lambda: timing.active_remaining,
        )
        self.gateway.request_guard = self.guard

    def guard(self, prompt, attempt):
        reserve = max(1, len(prompt)) + self.output_limit
        if budgets_enabled() and len(prompt) > self.limits.max_context_characters:
            raise ValueError("context_budget_exhausted")
        if (
            budgets_enabled()
            and self.attempts >= self.limits.max_model_calls
        ):
            raise ValueError("model_call_budget_exhausted")
        if token_budget_exceeded(
            self.tokens.used + reserve, self.limits.max_total_tokens
        ):
            raise ValueError("local_token_budget_exhausted")
        self.reservation = self.tokens.reserve(reserve)
        if self.reservation is None:
            raise ValueError("shared_token_budget_exhausted")
        self.attempts += 1

    async def generate(self, prompt):
        """Raw delegate used by ModelGateway; callers use call() for pacing/retries."""
        with self.timing.quota_wait() as waiting:
            quota = await within_deadline(
                self.pacer.acquire(
                    max(1, len(prompt)) + self.output_limit,
                    on_wait=lambda seconds, reasons: waiting.update(
                        reason="+".join(reasons),
                        until=self.timing.clock() + seconds,
                        source="global_rolling_window"
                        if self.pacer.scope is not None
                        else "local_rolling_window",
                    ),
                ),
                self.timing,
            )
        request_model = self._request_model.get()
        response = await (request_model or self.model).ainvoke(
            [HumanMessage(content=prompt)], **self.options
        )
        if request_model is not None:
            # Keep the raw JSON for strict canonical validation, including duplicate
            # key rejection. Never trust a wrapper's permissively parsed dictionary.
            response = response["raw"]
        usage = getattr(response, "usage_metadata", None)
        if (
            isinstance(usage, dict)
            and isinstance(usage.get("input_tokens"), int)
            and isinstance(usage.get("output_tokens"), int)
        ):
            actual = usage["input_tokens"] + usage["output_tokens"]
            self.reservation.settle(actual)
            self.pacer.settle(quota, actual)
        return response

    async def call(self, prompt, *, schema: type[BaseModel] | None = None):
        request_model = None
        factory = getattr(self.model, "with_structured_output", None)
        if schema is not None and callable(factory):
            try:
                request_model = factory(
                    lean_schema(schema), method="json_schema", include_raw=True
                )
            except NotImplementedError:
                pass  # Custom adapters retain the strict JSON fallback.
        token = self._request_model.set(request_model)
        try:
            response = await self.gateway(prompt, return_response=schema is not None)
            if schema is not None:
                diagnostic = finish_diagnostic(response)
                if diagnostic:
                    raise ValueError(diagnostic.removeprefix("; "))
            return response
        finally:
            self._request_model.reset(token)
