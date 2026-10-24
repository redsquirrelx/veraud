"""Process-independent rolling quotas shared by every caller of a provider/model."""

import asyncio
import math
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from config.agents.user import ProviderRateLimits


class RequestTokenQuotaExceeded(ValueError):
    """A request cannot fit the configured rolling-minute token quota."""


def quota_scope(provider, model):
    provider = provider.lower().strip()
    provider = {"google": "gemini"}.get(provider, provider)
    return provider + ":" + model.strip().removeprefix("models/")


def mark_quota_scope(model, settings):
    if model is None:
        return model
    object.__setattr__(model, "_provider_quota_scope", quota_scope(settings.provider, settings.name))
    return model


def model_quota_scope(model):
    scope = getattr(model, "_provider_quota_scope", None)
    if isinstance(scope, str):
        return scope
    settings = getattr(model, "settings", None)
    if isinstance(getattr(settings, "provider", None), str) and isinstance(getattr(settings, "name", None), str):
        return quota_scope(settings.provider, settings.name)
    # Native models supplied by standalone runners may bypass our factories.
    kind = getattr(model, "_llm_type", None)
    provider = {"chat-google-generative-ai": "gemini", "openai-chat": "openai", "anthropic-chat": "anthropic"}.get(kind) \
        if isinstance(kind, str) else None
    name = getattr(model, "model_name", None) or getattr(model, "model", None)
    if provider is not None and isinstance(name, str):
        base = str(getattr(model, "openai_api_base", "") or "")
        if provider == "openai":
            provider = "openrouter" if "openrouter.ai" in base else "groq" if "api.groq.com" in base else provider
        return quota_scope(provider, name)
    return None


@dataclass
class GlobalReservation:
    id: int
    started_at: float
    tokens: int


class QuotaStore:
    """SQLite transactions make admission atomic across tasks, loops and workers.

    Active policies share the strictest non-null bound. Policy leases expire
    after 60 seconds without admission attempts; reservations survive restarts.
    Credentials are never part of the scope or persisted here.
    """

    def __init__(self, path, *, clock=time.time):
        self.path, self.clock = str(path), clock
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS quota_request (
                    id INTEGER PRIMARY KEY, scope TEXT NOT NULL, started REAL NOT NULL, tokens INTEGER NOT NULL);
                CREATE INDEX IF NOT EXISTS quota_request_scope ON quota_request(scope, started);
                CREATE TABLE IF NOT EXISTS quota_policy (
                    scope TEXT NOT NULL, policy TEXT NOT NULL, rpm INTEGER, tpm INTEGER, seen REAL NOT NULL,
                    PRIMARY KEY(scope, policy));
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=1)
        try:
            with db:
                yield db
        finally:
            db.close()

    def acquire(self, scope, limits, tokens):
        now = self.clock()
        rpm, tpm = limits.requests_per_minute, limits.tokens_per_minute
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM quota_request WHERE started <= ?", (now - 60,))
            db.execute("DELETE FROM quota_policy WHERE seen <= ?", (now - 60,))
            db.execute("INSERT INTO quota_policy VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(scope, policy) DO UPDATE SET seen=excluded.seen",
                (scope, f"{rpm}:{tpm}", rpm, tpm, now))
            rpm, tpm = db.execute("SELECT MIN(rpm), MIN(tpm) FROM quota_policy WHERE scope=?", (scope,)).fetchone()
            if tpm is not None and tokens > tpm:
                # Commit the policy even when this particular request cannot fit.
                db.commit()
                raise RequestTokenQuotaExceeded("Request token reservation exceeds configured global TPM.")
            records = db.execute("SELECT started, tokens FROM quota_request WHERE scope=? ORDER BY started, id", (scope,)).fetchall()
            delays = {}
            if rpm is not None and len(records) >= rpm:
                delays["rpm"] = records[len(records) - rpm][0] + 60 - now
            if tpm is not None:
                excess = sum(record[1] for record in records) + tokens - tpm
                if excess > 0:
                    for started, used in records:
                        excess -= used
                        if excess <= 0:
                            delays["tpm"] = started + 60 - now
                            break
            if delays:
                return None, delays
            cursor = db.execute("INSERT INTO quota_request(scope, started, tokens) VALUES (?, ?, ?)", (scope, now, tokens))
            return GlobalReservation(cursor.lastrowid, now, tokens), {}

    def settle(self, reservation, tokens):
        with self.connect() as db:
            db.execute("UPDATE quota_request SET tokens=? WHERE id=? AND started=?", (tokens, reservation.id, reservation.started_at))
        reservation.tokens = tokens


@lru_cache(maxsize=1)
def global_quota_store():
    from ...config.settings import REPO_ROOT, get_server_settings

    try:
        configured = get_server_settings().provider_quota_path
    except ValueError:
        configured = ""
    return QuotaStore(Path(configured) if configured else REPO_ROOT / "appdata" / "provider-quotas.sqlite3")


async def acquire_global(scope, limits, tokens, *, on_wait=None):
    store = global_quota_store()
    last_wait = None
    while True:
        reservation, delays = store.acquire(scope, limits, tokens)
        if reservation is not None:
            return reservation
        delay = max(delays.values())
        reasons = sorted(delays)
        until = asyncio.get_running_loop().time() + delay
        if on_wait is not None and (last_wait is None or last_wait[0] != reasons or abs(last_wait[1] - until) > 1):
            on_wait(delay, reasons)
            last_wait = (reasons, until)
        # Recheck early when another process settles a conservative reservation.
        await asyncio.sleep(min(delay, 1))


def reported_tokens(response):
    usage = getattr(response, "usage_metadata", None)
    if isinstance(usage, dict):
        total = usage.get("total_tokens")
        if isinstance(total, int):
            return total
        incoming, outgoing = usage.get("input_tokens"), usage.get("output_tokens")
        if isinstance(incoming, int) and isinstance(outgoing, int):
            return incoming + outgoing
    total = getattr(usage, "total_token_count", None)
    if isinstance(total, int):
        return total
    total = getattr(getattr(response, "usage", None), "total_tokens", None)
    return total if isinstance(total, int) else None


def acquire_global_sync(scope, limits, tokens):
    while True:
        reservation, delays = global_quota_store().acquire(scope, limits, tokens)
        if reservation is not None:
            return reservation
        time.sleep(min(max(delays.values()), 1))


async def quota_generate(model, prompt, operation, *, max_output_tokens=None):
    """Provider-adapter boundary: every retry/probe/direct call acquires a slot."""
    limit = model.settings.max_tokens if max_output_tokens is None else max_output_tokens
    reservation = await acquire_global(model_quota_scope(model), ProviderRateLimits(), math.ceil(len(str(prompt)) * 0.5) + limit)
    response = await operation()
    actual = reported_tokens(response)
    if actual is not None:
        global_quota_store().settle(reservation, actual)
    return response
