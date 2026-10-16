"""Report cumulative usage without coupling agents to backend HTTP."""

import math

from ..benchmark.telemetry import response_usage
from ..config.logs import get_logger
from ..infrastructure.callback.schemas import ExecutionProgress
from ..runtimes.repository.model_runtime import extract_text
from ..runtimes.repository.token_budget import account_tokens

logger = get_logger("usage-reporting")


async def report_progress(callbacks, execution_id, usage):
    if callbacks is None or execution_id is None:
        return
    try:
        await callbacks.progress(execution_id, usage)
    except Exception as error:  # noqa: BLE001 - Callback transport must not discard model work.
        logger.warning("Usage callback for execution %s failed (%s)", execution_id, type(error).__name__)


def gateway_progress(gateway, budget):
    totals = gateway.usage_totals()
    _, estimated = account_tokens(gateway, budget)
    return ExecutionProgress(
        input_tokens=totals["reported_input_tokens"]
        if any(call["input_tokens"] is not None for call in gateway.calls) else None,
        output_tokens=totals["reported_output_tokens"]
        if any(call["output_tokens"] is not None for call in gateway.calls) else None,
        estimated_tokens=estimated,
    )


class ReportingModel:
    """Transparent model decorator for agents that don't use ModelGateway."""

    def __init__(self, delegate, callbacks, execution_id):
        self.delegate = delegate
        self.callbacks = callbacks
        self.execution_id = execution_id
        self.usage = ExecutionProgress()

    def __getattr__(self, name):
        return getattr(self.delegate, name)

    async def generate(self, message):
        try:
            response = await self.delegate.generate(message)
        except BaseException:
            self.usage.estimated_tokens += math.ceil(len(message) / 4) + self.settings.max_tokens
            await report_progress(self.callbacks, self.execution_id, self.usage)
            raise
        counts = response_usage(response)
        for name in ("input_tokens", "output_tokens"):
            count = counts[name]
            if count is not None:
                setattr(self.usage, name, (getattr(self.usage, name) or 0) + count)
            else:
                text = message if name == "input_tokens" else extract_text(response)
                self.usage.estimated_tokens += math.ceil(len(text) / 4)
        await report_progress(self.callbacks, self.execution_id, self.usage)
        return response
