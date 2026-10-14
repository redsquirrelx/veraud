"""Shared pacing and transient-error recovery across every benchmark stage."""

import asyncio
import math
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx


def http_status(error: Exception) -> int | None:
    response = getattr(error, "response", None)
    for value in (
        getattr(error, "status_code", None),
        getattr(error, "code", None),
        getattr(response, "status_code", None),
    ):
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def retryable(error: Exception) -> bool:
    status = http_status(error)
    if status is not None:
        return status in (408, 429, 500, 502, 503, 504)
    return isinstance(error, (TimeoutError, httpx.TransportError)) or type(error).__name__ in (
        "APIConnectionError", "APITimeoutError",
    )


def retry_after(error: Exception) -> float:
    """Read HTTP retry hints and Gemini's structured google.rpc.RetryInfo."""
    waits = []

    def seconds(value, scale=1):
        try:
            number = float(value) * scale
        except (TypeError, ValueError):
            return
        if math.isfinite(number) and number >= 0:
            waits.append(number)

    response = getattr(error, "response", None)
    headers = getattr(response, "headers", {}) or {}
    value = headers.get("retry-after")
    if value is not None:
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=UTC)
            seconds((date - datetime.now(UTC)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            seconds(value)
    seconds(headers.get("retry-after-ms"), 0.001)
    details = getattr(error, "details", None)
    if isinstance(details, dict):
        payload = details.get("error", details)
        if isinstance(payload, dict):
            for detail in payload.get("details", []) or []:
                if not isinstance(detail, dict):
                    continue
                if str(detail.get("@type", "")).endswith("google.rpc.RetryInfo"):
                    delay = detail.get("retryDelay")
                    if isinstance(delay, str) and delay.endswith("s"):
                        seconds(delay[:-1])
    return max(waits, default=0.0)


class RequestPacer:
    def __init__(self, interval=12.0, max_retries=3, backoff=30.0):
        self.interval = interval
        self.max_retries = max_retries
        self.backoff = backoff
        self.lock = asyncio.Lock()
        self.next_allowed = 0.0

    async def wait(self) -> float:
        delay = max(0.0, self.next_allowed - time.monotonic())
        if delay:
            await asyncio.sleep(delay)
        return delay

    def completed_attempt(self):
        # Pause after a completed adapter attempt, not merely between starts.
        self.next_allowed = max(self.next_allowed, time.monotonic() + self.interval)

    def cooldown(self, error: Exception, retry_index: int) -> float:
        delay = max(retry_after(error), min(120.0, self.backoff * 2 ** min(retry_index, 10)))
        self.next_allowed = max(self.next_allowed, time.monotonic() + delay)
        return delay
