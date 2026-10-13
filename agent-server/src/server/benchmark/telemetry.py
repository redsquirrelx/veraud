"""Observe model calls, including shared pacing and retry attempts."""

import asyncio
import hashlib
import time
from typing import Any

from ..agents.analyzer.parsing import extract_text, parse_json
from ..agents.models.base import Model
from ..services.collection.service import CollectionService
from .pacing import RequestPacer, http_status, retryable


def response_usage(response: Any) -> dict[str, int | None]:
    usage = getattr(response, "usage_metadata", None) or {}
    metadata = getattr(response, "response_metadata", None) or {}
    if not usage:
        usage = metadata.get("token_usage", {})

    def count(*keys):
        for key in keys:
            value = usage.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                return value
        return None

    return {
        "input_tokens": count("input_tokens", "prompt_tokens"),
        "output_tokens": count("output_tokens", "completion_tokens"),
    }


class MeasuredModel(Model):
    def __init__(self, delegate: Model, pacer: RequestPacer | None = None):
        super().__init__(delegate.settings, delegate.credentials)
        self.delegate = delegate
        self.pacer = pacer
        self.calls: list[dict] = []

    async def generate(self, message: str) -> Any:
        started = time.perf_counter()
        call = {
            "prompt_chars": len(message),
            "prompt_sha256": hashlib.sha256(message.encode()).hexdigest(),
            "status": "completed",
            "input_tokens": None,
            "output_tokens": None,
            "attempts": [],
            "wait_seconds": 0.0,
        }
        try:
            if self.pacer is None:
                response = await self._attempt(message, call)
            else:
                async with self.pacer.lock:
                    response = await self._paced_generate(message, call)
            call.update(response_usage(response))
            text = extract_text(response)
            call["response_chars"] = len(text)
            try:
                parse_json(text)
                call["valid_json_object"] = True
            except (ValueError, TypeError):
                call["valid_json_object"] = False
            return response
        except asyncio.CancelledError:
            call["status"] = "cancelled"
            raise
        except Exception as error:
            call["status"] = "failed"
            # Provider exception messages can contain credentials or request data.
            call["error_type"] = type(error).__name__
            call["http_status"] = http_status(error)
            raise
        finally:
            call["seconds"] = time.perf_counter() - started
            self.calls.append(call)

    async def _attempt(self, message: str, call: dict):
        started = time.perf_counter()
        attempt = {"status": "completed"}
        try:
            return await self.delegate.generate(message)
        except asyncio.CancelledError:
            attempt["status"] = "cancelled"
            raise
        except Exception as error:
            attempt.update(status="failed", error_type=type(error).__name__, http_status=http_status(error))
            raise
        finally:
            attempt["seconds"] = time.perf_counter() - started
            call["attempts"].append(attempt)
            if self.pacer is not None:
                self.pacer.completed_attempt()

    async def _paced_generate(self, message: str, call: dict):
        for retry_index in range(self.pacer.max_retries + 1):
            waiting = time.perf_counter()
            try:
                call["wait_seconds"] += await self.pacer.wait()
            except asyncio.CancelledError:
                call["wait_seconds"] += time.perf_counter() - waiting
                raise
            try:
                return await self._attempt(message, call)
            except Exception as error:
                if not retryable(error):
                    raise
                delay = self.pacer.cooldown(error, retry_index)
                code = http_status(error)
                label = f"HTTP {code}" if code is not None else type(error).__name__
                if retry_index >= self.pacer.max_retries:
                    print(f"    proveedor: {label}; reintentos agotados, pausa compartida de al menos {delay:.1f}s", flush=True)
                    raise
                print(f"    proveedor: {label}; reintento {retry_index + 1}/{self.pacer.max_retries} en al menos {delay:.1f}s", flush=True)


class MeasuredCollection(CollectionService):
    def __init__(self):
        super().__init__()
        self.observations: list[dict] = []

    async def collect(self, input_data):
        started = time.perf_counter()
        result = await super().collect(input_data)
        self.observations.append({
            "seconds": time.perf_counter() - started,
            "limits": input_data.model_dump(),
            "stats": result.stats,
            "mapped_paths": [item["path"] for item in result.repo_map["files"]],
        })
        return result


def call_metrics(calls: list[dict], input_price: float | None, output_price: float | None):
    measured = [call for call in calls if call["input_tokens"] is not None and call["output_tokens"] is not None]
    attempts = [attempt for call in calls for attempt in call.get("attempts", [])]
    complete = bool(calls) and len(measured) == len(calls) and all(attempt["status"] == "completed" for attempt in attempts)
    input_tokens = sum(call["input_tokens"] for call in measured)
    output_tokens = sum(call["output_tokens"] for call in measured)
    cost = None
    if complete and input_price is not None and output_price is not None:
        cost = (input_tokens * input_price + output_tokens * output_price) / 1_000_000
    return {
        "calls": len(calls),
        "failed_calls": sum(call["status"] == "failed" for call in calls),
        "cancelled_calls": sum(call["status"] == "cancelled" for call in calls),
        "invalid_json_calls": sum(call.get("valid_json_object") is False for call in calls),
        "model_seconds": sum(sum(attempt["seconds"] for attempt in call["attempts"]) if "attempts" in call else call["seconds"] for call in calls),
        "wait_seconds": sum(call.get("wait_seconds", 0.0) for call in calls),
        "retry_attempts": sum(max(0, len(call.get("attempts", [])) - 1) for call in calls),
        "rate_limit_events": sum(attempt.get("http_status") == 429 for attempt in attempts),
        "prompt_chars": sum(call["prompt_chars"] for call in calls),
        "usage_calls": len(measured),
        "usage_complete": complete,
        "observed_input_tokens": input_tokens if measured else None,
        "observed_output_tokens": output_tokens if measured else None,
        "cost_usd": cost,
    }
