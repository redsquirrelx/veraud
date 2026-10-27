"""Shared pacing and transient-error recovery across every benchmark stage."""

import asyncio
import math
import time
from dataclasses import dataclass
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


def daily_quota_exhausted(error: Exception) -> bool:
    """An explicit daily quota rejection cannot recover through minute pacing."""
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        for name in ("details", "body", "response_json"):
            value = getattr(error, name, None)
            payload = value.get("error", value) if isinstance(value, dict) else {}
            if not isinstance(payload, dict):
                continue
            for detail in payload.get("details", []) or []:
                if not isinstance(detail, dict) or not str(detail.get("@type", "")).endswith("google.rpc.QuotaFailure"):
                    continue
                for violation in detail.get("violations", []) or []:
                    if isinstance(violation, dict) and "perday" in str(violation.get("quotaId", "")).lower().replace("_", ""):
                        return True
        error = error.__cause__ or error.__context__
    return False


def retryable(error: Exception) -> bool:
    if daily_quota_exhausted(error):
        return False
    status = http_status(error)
    if status is not None:
        return status in (408, 429, 500, 502, 503, 504)
    return isinstance(error, (TimeoutError, httpx.TransportError)) or type(error).__name__ in (
        "APIConnectionError", "APITimeoutError",
    )


@dataclass(frozen=True)
class RetryHint:
    seconds: float
    source: str


def retry_hints(error: Exception) -> list[RetryHint]:
    """Parse provider retry hints with units and provenance, without raw payloads."""
    waits = []

    def seconds(value, source, scale=1):
        try:
            number = float(value) * scale
        except (TypeError, ValueError):
            return
        if math.isfinite(number) and number >= 0:
            waits.append(RetryHint(number, source))

    response = getattr(error, "response", None)
    headers = getattr(response, "headers", {}) or {}
    value = headers.get("retry-after")
    if value is not None:
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=UTC)
            seconds(max(0, (date - datetime.now(UTC)).total_seconds()), "retry-after.http-date")
        except (TypeError, ValueError, OverflowError):
            seconds(value, "retry-after.seconds")
    seconds(headers.get("retry-after-ms"), "retry-after-ms", 0.001)
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
                        seconds(delay[:-1], "google.rpc.RetryInfo.retryDelay")
    return waits


def retry_after(error: Exception) -> float:
    """Compatibility scalar for benchmark callers; all hints belong to this response."""
    return max((hint.seconds for hint in retry_hints(error)), default=0.0)


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
