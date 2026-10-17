"""Safe provider classification through adapter exception chains; no raw payload logging."""

import asyncio
import re
from collections import deque
from dataclasses import dataclass
from time import monotonic

from config.agents.provider import ProviderRetryConfig

from ...benchmark.pacing import RequestPacer, http_status, retry_hints, retryable


class RequestTokenQuotaExceeded(ValueError):
    """A single request cannot fit the configured rolling-minute token quota."""


@dataclass
class QuotaReservation:
    started_at: float
    tokens: int


class ProviderPacer(RequestPacer):
    """Shared rolling-60-second admission and local request pacing.

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
        # No await: atomic within the event loop, also while another caller waits.
        # An expired reservation no longer affects the current rolling window.
        reservation.tokens = actual_tokens
        self._notify()

    def _notify(self):
        # Broadcast without clearing an event another waiter still needs to see.
        notification, self.changed = self.changed, asyncio.Event()
        notification.set()


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


def retry_hint(error):
    """Prefer the original provider response over duplicated/translated wrapper hints."""
    for cause in reversed(list(causes(error))):
        hints = retry_hints(cause)
        if hints:
            return max(hints, key=lambda hint: hint.seconds)
    return None


def retry_delay(error):
    hint = retry_hint(error)
    return hint.seconds if hint is not None else 0


def quota_facts(error):
    """Only protocol quota identifiers/classifications, never descriptions or project IDs."""
    facts = []
    for cause in reversed(list(causes(error))):
        details = getattr(cause, "details", None)
        if not isinstance(details, dict):
            continue
        payload = details.get("error", details)
        if not isinstance(payload, dict):
            continue
        for detail in payload.get("details", []) or []:
            if not isinstance(detail, dict) or not str(detail.get("@type", "")).endswith("google.rpc.QuotaFailure"):
                continue
            for violation in detail.get("violations", []) or []:
                if not isinstance(violation, dict):
                    continue
                quota_id = violation.get("quotaId", "")
                metric = violation.get("quotaMetric", "")
                for name, value in (("quota_id", quota_id), ("quota_metric", metric)):
                    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_./:-]{1,200}", value):
                        facts.append(f"{name}={value}")
                kind = (str(quota_id) + " " + str(metric)).lower().replace("_", "")
                if "perday" in kind:
                    facts.append("quota_window=day")
                elif "perminute" in kind:
                    facts.append("quota_window=minute")
        if facts:
            break
    return list(dict.fromkeys(facts))


def response_payload(cause):
    """Read structured error bodies across SDK versions; callers allowlist output."""
    for name in ("details", "body", "response_json"):
        value = getattr(cause, name, None)
        if isinstance(value, dict) and value:
            return value.get("error", value)
    response = getattr(cause, "response", None)
    if callable(getattr(response, "json", None)):
        try:
            value = response.json()
        except (ValueError, TypeError, RuntimeError):
            return {}
        if isinstance(value, dict):
            return value.get("error", value)
    return {}


def request_facts(error):
    """Allowlisted request field names from structured Google BadRequest details."""
    aliases = {
        "response_schema": "response_schema", "responseSchema": "response_schema",
        "response_json_schema": "response_json_schema", "responseJsonSchema": "response_json_schema",
        "max_output_tokens": "max_output_tokens", "maxOutputTokens": "max_output_tokens",
        "temperature": "temperature", "tools": "tools", "contents": "contents",
        "thinking_config": "thinking_config", "thinkingConfig": "thinking_config",
        "tool_config": "tool_config", "toolConfig": "tool_config",
        "response_mime_type": "response_mime_type", "responseMimeType": "response_mime_type",
    }
    facts = []
    for cause in reversed(list(causes(error))):
        payload = response_payload(cause)
        if not isinstance(payload, dict) or not isinstance(payload.get("details", []), list):
            continue
        for detail in payload.get("details", [])[:8]:
            if not isinstance(detail, dict) or not str(detail.get("@type", "")).endswith("google.rpc.BadRequest"):
                continue
            violations = detail.get("fieldViolations", [])
            if not isinstance(violations, list):
                continue
            for violation in violations[:8]:
                field = violation.get("field") if isinstance(violation, dict) else None
                if isinstance(field, str):
                    parts = re.split(r"[.\[\]]", field)
                    # The first known request field is sufficient; nested schema
                    # property names and violation descriptions must never escape.
                    name = next((aliases[part] for part in parts if part in aliases), None)
                    if name:
                        facts.append(f"request_field={name}")
    return list(dict.fromkeys(facts))


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
        "model_prefilling": ("does not support model prefilling",),
        "unsupported_thinking": ("thinking is not supported", "thinking budget is not supported"),
    }
    facts.extend(name for name, patterns in categories.items() if any(p in text for p in patterns))
    hint = retry_hint(error)
    if hint is not None:
        facts.extend((f"retry_after_seconds={hint.seconds:g}", f"retry_after_source={hint.source}"))
    facts.extend(quota_facts(error))
    facts.extend(request_facts(error))
    if status == 400 and not any(fact.startswith("request_field=") for fact in facts):
        facts.append("request_field=not_reported")
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
