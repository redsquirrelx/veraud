"""Safe provider classification through adapter exception chains; no raw payload logging."""

import asyncio
from collections import deque
from dataclasses import dataclass
from time import monotonic

from config.agents.provider import ProviderRetryConfig

from ...benchmark.pacing import RequestPacer, http_status, retry_after, retryable


class RequestTokenQuotaExceeded(ValueError):
    """A single request cannot fit the configured rolling-minute token quota."""


@dataclass
class QuotaReservation:
    started_at: float
    tokens: int


class ProviderPacer(RequestPacer):
    """Shared rolling-60-second admission, combined with pacing and cooldown.

    Ledger timestamps belong to request starts, not calendar-minute boundaries.
    Failed/unknown attempts retain their token estimates. The caller owns scope:
    one instance per assessment by default; inject the same instance across runs
    to enforce a shared in-process project/model quota. No cross-process persistence.
    """

    def __init__(self, *, rate_limits, interval=None, max_retries=None, backoff=None,
                 provider_config=None, clock=monotonic, sleep=asyncio.sleep):
        policy = provider_config or ProviderRetryConfig()
        interval = policy.provider_request_interval_seconds if interval is None else interval
        max_retries = policy.max_provider_retries if max_retries is None else max_retries
        backoff = policy.provider_retry_backoff_seconds if backoff is None else backoff
        super().__init__(interval=interval, max_retries=max_retries, backoff=backoff)
        self.rate_limits = rate_limits
        self.reservations = deque()
        self.clock = clock
        self.sleep = sleep
        self.changed = asyncio.Event()

    def quota_delay(self, tokens, now):
        limits = self.rate_limits
        if limits.tokens_per_minute is not None and tokens > limits.tokens_per_minute:
            raise RequestTokenQuotaExceeded("Request token reservation exceeds configured TPM.")
        while self.reservations and self.reservations[0].started_at <= now - 60:
            self.reservations.popleft()
        delays = {}
        if limits.requests_per_minute is not None and len(self.reservations) >= limits.requests_per_minute:
            index = len(self.reservations) - limits.requests_per_minute
            delays["rpm"] = self.reservations[index].started_at + 60 - now
        if limits.tokens_per_minute is not None:
            excess = sum(r.tokens for r in self.reservations) + tokens - limits.tokens_per_minute
            if excess > 0:
                for record in self.reservations:
                    excess -= record.tokens
                    if excess <= 0:
                        delays["tpm"] = record.started_at + 60 - now
                        break
        return delays

    async def acquire(self, tokens, *, on_wait=None):
        async with self.lock:
            while True:
                self.changed.clear()
                now = self.clock()
                delays = self.quota_delay(tokens, now)
                if self.next_allowed > now:
                    delays["pacing_or_cooldown"] = self.next_allowed - now
                delay = max(delays.values(), default=0)
                if delay <= 0:
                    reservation = QuotaReservation(now, tokens)
                    self.reservations.append(reservation)
                    self.next_allowed = max(self.next_allowed, now + self.interval)
                    return reservation
                if on_wait is not None:
                    on_wait(delay, sorted(delays))
                sleeper = asyncio.create_task(self.sleep(delay))
                changed = asyncio.create_task(self.changed.wait())
                try:
                    done, _ = await asyncio.wait((sleeper, changed), return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        task.result()
                finally:
                    for task in (sleeper, changed):
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(sleeper, changed, return_exceptions=True)

    def settle(self, reservation, actual_tokens):
        # No await: atomic within the event loop, also while another caller waits.
        # An expired reservation no longer affects the current rolling window.
        reservation.tokens = actual_tokens
        self.changed.set()


def causes(error):
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        yield error
        error = error.__cause__ or error.__context__


def provider_status(error):
    return next((status for cause in causes(error) if (status := http_status(cause)) is not None), None)


def transient(error):
    return any(retryable(cause) for cause in causes(error))


def retry_delay(error):
    return max((retry_after(cause) for cause in causes(error)), default=0)


def provider_diagnostic(error):
    """Emit only codes and fixed classifications, never an exception's raw message."""
    status = provider_status(error)
    facts = [f"http_status={status}"] if status is not None else []
    text = " ".join(str(cause).lower() for cause in causes(error))
    categories = {
        "schema_complexity": ("too many states", "schema is too complex", "schema has too many", "schema complexity"),
        "unsupported_schema": ("unsupported schema", "unsupported keyword", "unknown name", "not supported in the schema"),
        "invalid_argument": ("invalid_argument",),
        "quota_exhausted": ("resource_exhausted", "quota exceeded", "rate limit"),
        "authentication": ("unauthenticated", "api key not valid"),
    }
    facts.extend(name for name, patterns in categories.items() if any(p in text for p in patterns))
    delay = retry_delay(error)
    if delay:
        facts.append(f"retry_after_seconds={delay:g}")
    return "; " + ", ".join(facts) if facts else ""


def lean_schema(schema):
    """Remove generation hints that inflate native schema complexity.

    Local Pydantic validation still enforces every bound and rejects extra fields.
    Keep types, required fields, enums, refs and nullability intact.
    """
    hints = {"minItems", "maxItems", "minLength", "maxLength", "minimum", "maximum", "default", "description"}

    def visit(value):
        if isinstance(value, dict):
            return {key: ({name: visit(child) for name, child in item.items()}
                          if key in {"properties", "$defs"} else visit(item))
                    for key, item in value.items() if key not in hints}
        if isinstance(value, list):
            return [visit(item) for item in value]
        return value

    return visit(schema.model_json_schema())
