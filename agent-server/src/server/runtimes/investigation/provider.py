"""Safe provider classification through adapter exception chains; no raw payload logging."""

import asyncio
from collections import deque
from dataclasses import dataclass
from time import monotonic

from config.agents.provider import ProviderRetryConfig
from server.infrastructure.llm.diagnostics import (
    causes,
    provider_diagnostic,
    provider_status,
    quota_facts,
    request_facts,
    response_payload,
    retry_delay,
    retry_hint,
    transient,
)
from server.infrastructure.llm.retry import (
    RequestPacer,
    http_status,
    retry_hints,
    retryable,
)

from ...infrastructure.llm.quota import (
    GlobalReservation,
    RequestTokenQuotaExceeded,
    acquire_global,
    global_quota_store,
    model_quota_scope,
)

__all__ = [
    "GlobalReservation", "ProviderPacer", "QuotaReservation", "RequestPacer",
    "RequestTokenQuotaExceeded", "acquire_global", "causes", "global_quota_store",
    "http_status", "lean_schema", "model_pacer", "model_quota_scope",
    "provider_diagnostic", "provider_status", "quota_facts", "request_facts",
    "response_payload", "retry_delay", "retry_hint", "retry_hints", "retryable",
    "transient",
]


@dataclass
class QuotaReservation:
    started_at: float
    tokens: int


class ProviderPacer(RequestPacer):
    """Shared rolling-60-second admission and local request pacing.

    Ledger timestamps belong to request starts, not calendar-minute boundaries.
    Failed/unknown attempts retain their token estimates. Provider-backed models
    use a persistent provider/model scope shared across runs and OS processes.
    Anonymous offline models can still inject an in-memory pacer/virtual clock.
    """

    def __init__(self, *, rate_limits, interval=None, max_retries=None, backoff=None,
                 provider_config=None, clock=monotonic, sleep=asyncio.sleep, scope=None):
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
        self.scope = scope

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
        if self.scope is not None:
            # Global admission replaces local RPM/TPM counters; the existing
            # invocation pacer still owns its independent minimum spacing.
            if self.interval == 0:
                return await acquire_global(self.scope, self.rate_limits, tokens, on_wait=on_wait)
            async with self.lock:
                await self.wait()
                reservation = await acquire_global(self.scope, self.rate_limits, tokens, on_wait=on_wait)
                self.completed_attempt()
                return reservation
        while True:
            # Only checking/reserving capacity is serialized. A sleeping request
            # must not hold up smaller requests that fit the available TPM.
            async with self.lock:
                notification = self.changed
                now = self.clock()
                delays = self.quota_delay(tokens, now)
                if self.next_allowed > now:
                    delays["pacing"] = self.next_allowed - now
                delay = max(delays.values(), default=0)
                if delay <= 0:
                    reservation = QuotaReservation(now, tokens)
                    self.reservations.append(reservation)
                    self.next_allowed = max(self.next_allowed, now + self.interval)
                    return reservation
                if on_wait is not None:
                    on_wait(delay, sorted(delays))
            sleeper = asyncio.create_task(self.sleep(delay))
            changed = asyncio.create_task(notification.wait())
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
        if isinstance(reservation, GlobalReservation):
            global_quota_store().settle(reservation, actual_tokens)
            return
        # No await: atomic within the event loop, also while another caller waits.
        # An expired reservation no longer affects the current rolling window.
        reservation.tokens = actual_tokens
        self._notify()

    def _notify(self):
        # Broadcast without clearing an event another waiter still needs to see.
        notification, self.changed = self.changed, asyncio.Event()
        notification.set()


def model_pacer(model, *, injected=None, **options):
    scope = model_quota_scope(model)
    if scope is None and injected is not None:
        return injected
    return ProviderPacer(scope=scope, **options)




















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
