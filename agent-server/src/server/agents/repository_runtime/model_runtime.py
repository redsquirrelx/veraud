"""Provider execution, bounded retries, telemetry, and client cleanup."""

import asyncio
import math
from time import monotonic
from types import SimpleNamespace

from ...benchmark.pacing import RequestPacer, http_status, retry_after, retryable
from ...benchmark.telemetry import response_usage
from .telemetry import ModelCallMeasurement, execution_telemetry, measured_prompt


def extract_text(response: object) -> str:
    """Normalize whatever the model client returns into a string."""
    if response is None:
        return ""
    if isinstance(response, str):
        return response

    content = getattr(response, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )

    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text

    return str(response)


class ModelGateway:
    """One shared pacer for the full run; the runner owns the delegate client."""

    def __init__(
        self,
        delegate,
        *,
        interval=0,
        max_retries=2,
        backoff=2,
        on_event=None,
        trace=False,
        remaining_seconds=None,
        on_usage=None,
    ):
        if (
            not math.isfinite(interval)
            or not math.isfinite(backoff)
            or interval < 0
            or backoff < 0
            or max_retries < 0
        ):
            raise ValueError(
                "Provider pacing/retry limits must be finite and nonnegative."
            )
        self.delegate = delegate
        self.pacer = RequestPacer(
            interval=interval, max_retries=max_retries, backoff=backoff
        )
        self.calls = []
        self.measurements = []
        self.on_event = on_event
        self.trace = trace
        self.stopped = False
        self.remaining_seconds = remaining_seconds
        self.on_usage = on_usage

    async def __call__(self, prompt):
        if self.stopped:
            raise RuntimeError("Provider unavailable after a terminal failure.")
        record = {
            "attempts": 0,
            "wait_seconds": 0.0,
            "status": "failed",
            "input_tokens": None,
            "output_tokens": None,
            "unknown_usage_attempts": 0,
        }
        measurement = getattr(prompt, "measurement", None)
        if measurement is None:
            measurement = measured_prompt(
                [(prompt, "instructions")], stage="unknown"
            ).measurement
        response_characters = None
        delegate = self.delegate
        output_limit = getattr(prompt, "max_output_tokens", None)
        limited_generate = getattr(delegate, "generate_with_output_limit", None)
        if output_limit is not None and limited_generate is not None:

            async def generate_limited(text):
                return await limited_generate(text, max_output_tokens=output_limit)

            delegate = SimpleNamespace(
                generate=generate_limited,
                settings=getattr(self.delegate, "settings", None),
            )
        started = monotonic()
        call_number = len(self.calls) + 1
        wait_reason = "request_pacing_or_shared_cooldown"
        last_http_status = None

        def emit(event, **values):
            if self.on_event is not None:
                self.on_event(event, {"call": call_number, **values})

        emit(
            "model_call_started",
            stage=measurement.stage,
            correction=measurement.correction,
            prompt_characters=len(prompt),
            estimated_input_tokens=measurement.estimated_input_tokens,
            estimate_method=measurement.estimate_method,
            context_characters={
                part.category: part.characters for part in measurement.context
            },
        )
        try:
            async with self.pacer.lock:
                for index in range(self.pacer.max_retries + 1):
                    guard = getattr(self, "request_guard", None)
                    if guard is not None:
                        guard(prompt, record["attempts"])
                    delay = max(0, self.pacer.next_allowed - monotonic())
                    if delay:
                        emit(
                            "provider_wait",
                            wait_seconds=delay,
                            reason=wait_reason,
                            attempt=index + 1,
                            max_attempts=self.pacer.max_retries + 1,
                            http_status=last_http_status,
                        )
                    waiting = monotonic()
                    try:
                        await self.pacer.wait()
                    finally:
                        record["wait_seconds"] += monotonic() - waiting
                    record["attempts"] += 1
                    attempt_has_usage = False
                    emit(
                        "provider_request",
                        attempt=index + 1,
                        max_attempts=self.pacer.max_retries + 1,
                    )
                    try:
                        if self.trace:
                            from ...config.tracing import traced_generate

                            response = await traced_generate(delegate, str(prompt))
                        else:
                            response = await delegate.generate(str(prompt))
                        metadata = getattr(response, "usage_metadata", None)
                        if metadata is not None and hasattr(
                            metadata, "prompt_token_count"
                        ):
                            record.update(
                                input_tokens=metadata.prompt_token_count,
                                output_tokens=metadata.candidates_token_count,
                                status="completed",
                            )
                        else:
                            record.update(response_usage(response), status="completed")
                        attempt_has_usage = (
                            record["input_tokens"] is not None
                            and record["output_tokens"] is not None
                        )
                        text = extract_text(response)
                        if text.strip().startswith("```json") and text.strip().endswith(
                            "```"
                        ):
                            text = text.strip()[7:-3].strip()
                        response_characters = len(text)
                        return text
                    except Exception as error:
                        record["http_status"] = http_status(error)
                        record["error_type"] = type(error).__name__
                        emit(
                            "provider_error",
                            error_type=type(error).__name__,
                            http_status=http_status(error),
                        )
                        if index >= self.pacer.max_retries or not retryable(error):
                            self.stopped = True
                            raise
                        provider_delay = retry_after(error)
                        requested_wait = max(
                            provider_delay,
                            min(120.0, self.pacer.backoff * 2 ** min(index, 10)),
                            self.pacer.interval,
                            self.pacer.next_allowed - monotonic(),
                        )
                        remaining = (
                            self.remaining_seconds()
                            if self.remaining_seconds is not None
                            else None
                        )
                        if remaining is not None and requested_wait >= remaining:
                            self.stopped = True
                            emit(
                                "provider_retry_skipped",
                                reason="retry_wait_exceeds_remaining_budget",
                                requested_wait_seconds=round(requested_wait, 1),
                                remaining_budget_seconds=round(max(0, remaining), 1),
                                http_status=http_status(error),
                            )
                            raise
                        delay = self.pacer.cooldown(error, index)
                        last_http_status = http_status(error)
                        wait_reason = (
                            "provider_retry_after"
                            if provider_delay > 0 and provider_delay >= delay
                            else "retry_backoff"
                        )
                        emit(
                            "provider_retry",
                            retry=index + 1,
                            delay_seconds=delay,
                            provider_retry_after_seconds=provider_delay,
                            reason=wait_reason,
                            http_status=last_http_status,
                        )
                    finally:
                        if not attempt_has_usage:
                            record["unknown_usage_attempts"] += 1
                        self.pacer.completed_attempt()
        except asyncio.CancelledError:
            record["status"] = "cancelled"
            raise
        finally:
            record["seconds"] = monotonic() - started
            self.calls.append(record)
            self.measurements.append(
                ModelCallMeasurement(
                    **measurement.model_dump(),
                    call=call_number,
                    status=record["status"],
                    attempts=record["attempts"],
                    seconds=record["seconds"],
                    wait_seconds=record["wait_seconds"],
                    response_characters=response_characters,
                    input_tokens=record["input_tokens"],
                    output_tokens=record["output_tokens"],
                    unknown_usage_attempts=record["unknown_usage_attempts"],
                    http_status=record.get("http_status"),
                    error_type=record.get("error_type"),
                )
            )
            emit(
                "model_call_finished",
                stage=measurement.stage,
                status=record["status"],
                seconds=round(record["seconds"], 1),
                attempts=record["attempts"],
                input_tokens=record["input_tokens"],
                output_tokens=record["output_tokens"],
            )
            if self.on_usage is not None:
                await self.on_usage(self)

    def usage_totals(self):
        def token_total(name):
            return (
                sum(record[name] for record in self.calls)
                if self.calls
                and all(
                    record[name] is not None and not record["unknown_usage_attempts"]
                    for record in self.calls
                )
                else None
            )

        return {
            "provider_attempts": sum(record["attempts"] for record in self.calls),
            "provider_retries": sum(
                max(0, record["attempts"] - 1) for record in self.calls
            ),
            "provider_wait_seconds": sum(
                record["wait_seconds"] for record in self.calls
            ),
            "input_tokens": token_total("input_tokens"),
            "output_tokens": token_total("output_tokens"),
            "reported_input_tokens": sum(
                record["input_tokens"] or 0 for record in self.calls
            ),
            "reported_output_tokens": sum(
                record["output_tokens"] or 0 for record in self.calls
            ),
            "unknown_usage_attempts": sum(
                record["unknown_usage_attempts"] for record in self.calls
            ),
        }

    def telemetry(self, tool_requests=()):
        return execution_telemetry(self.measurements, tool_requests)


async def close_model_clients(model):
    """Release runner-owned clients on success, timeout, error, or cancellation."""
    failures = []
    client = getattr(model, "client", None)
    llm = getattr(model, "llm", None)
    operations = []
    if client is not None and hasattr(client, "aio"):
        operations.extend(((client.aio, "aclose"), (client, "close")))
    if llm is not None:
        operations.extend(
            (
                (getattr(llm, "root_async_client", None), "close"),
                (getattr(llm, "root_client", None), "close"),
            )
        )
    for resource, name in operations:
        if resource is None or not hasattr(resource, name):
            continue
        try:
            value = getattr(resource, name)()
            if hasattr(value, "__await__"):
                await value
        except Exception as error:  # noqa: BLE001 - attempt every cleanup without hiding the run result
            failures.append(type(error).__name__)
    return tuple(failures)


def create_project_model(settings, credentials):
    """Reuse provider adapters; honor Gemini JSON/sampling/output configuration."""
    from ...app.execution_service import build_model

    if settings.provider.lower() not in ("google", "gemini"):
        return build_model(settings, credentials)
    from ..models.gemini import GeminiModel

    class ConfiguredGeminiModel(GeminiModel):
        async def generate(self, message):
            return await self.generate_with_output_limit(
                message, max_output_tokens=self.settings.max_tokens
            )

        async def generate_with_output_limit(self, message, *, max_output_tokens):
            from google.genai import types

            return await self.client.aio.models.generate_content(
                model=self.settings.name,
                contents=str(message),
                config=types.GenerateContentConfig(
                    temperature=self.settings.temperature,
                    max_output_tokens=min(self.settings.max_tokens, max_output_tokens),
                    response_mime_type="application/json",
                ),
            )

    return ConfiguredGeminiModel(settings, credentials)
