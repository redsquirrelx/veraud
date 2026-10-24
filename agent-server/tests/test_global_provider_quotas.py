"""Global admission across independent runtimes and OS processes, without HTTP."""

import asyncio
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from config.agents.user import ProviderRateLimits
from server.infrastructure.llm import quota
from server.runtimes.investigation.provider import model_pacer


def test_concurrent_groups_and_another_process_share_one_rpm_window(tmp_path):
    path = tmp_path / "global.sqlite3"
    stores = [quota.QuotaStore(path, clock=lambda: 1000) for _ in range(3)]
    limits = ProviderRateLimits()

    def request(index):
        reservation, _ = stores[index % 3].acquire("gemini:model", limits, 16000)
        return reservation is not None

    with ThreadPoolExecutor(max_workers=6) as workers:
        accepted = list(workers.map(request, range(42)))
    assert sum(accepted) == 14
    script = """
import json, sys
from config.agents.user import ProviderRateLimits
from server.infrastructure.llm.quota import QuotaStore
reservation, delays = QuotaStore(sys.argv[1], clock=lambda: 1000).acquire('gemini:model', ProviderRateLimits(), 16000)
print(json.dumps({'accepted': reservation is not None, 'delays': delays}))
"""
    result = subprocess.run([sys.executable, "-c", script, str(path)], check=True, capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")})
    child = json.loads(result.stdout)
    assert not child["accepted"] and child["delays"]["rpm"] == 60


def test_aggregate_tpm_settlement_expiry_and_old_receipts(tmp_path):
    now = [1000]
    path = tmp_path / "global.sqlite3"
    first = quota.QuotaStore(path, clock=lambda: now[0])
    second = quota.QuotaStore(path, clock=lambda: now[0])
    limits = ProviderRateLimits(requests_per_minute=None, tokens_per_minute=250000)
    reservation, _ = first.acquire("gemini:model", limits, 200000)
    assert second.acquire("gemini:model", limits, 100000)[1] == {"tpm": 60}
    first.settle(reservation, 10000)
    assert second.acquire("gemini:model", limits, 200000)[0] is not None
    now[0] += 60
    fresh, _ = second.acquire("gemini:model", limits, 200000)
    first.settle(reservation, 0)  # Expired IDs may be reused; never alter the new receipt.
    assert second.acquire("gemini:model", limits, 100000)[0] is None
    assert fresh.tokens == 200000


def test_same_model_uses_strictest_active_policy_and_other_models_are_independent(tmp_path):
    now = [1000]
    store = quota.QuotaStore(tmp_path / "global.sqlite3", clock=lambda: now[0])
    strict = ProviderRateLimits(requests_per_minute=1, tokens_per_minute=1000)
    disabled = ProviderRateLimits(requests_per_minute=None, tokens_per_minute=None)
    assert store.acquire(quota.quota_scope("Google", "models/a"), strict, 1)[0] is not None
    assert store.acquire(quota.quota_scope("gemini", "a"), disabled, 1)[0] is None
    assert store.acquire(quota.quota_scope("gemini", "b"), strict, 1)[0] is not None
    with pytest.raises(quota.RequestTokenQuotaExceeded):
        store.acquire("gemini:a", disabled, 1001)
    now[0] += 60
    assert store.acquire("gemini:a", disabled, 1001)[0] is not None
    assert store.acquire("gemini:a", disabled, 1001)[0] is not None


def test_waiting_global_call_is_cancellable_without_a_request_reservation(monkeypatch, tmp_path):
    store = quota.QuotaStore(tmp_path / "global.sqlite3")
    monkeypatch.setattr(quota, "global_quota_store", lambda: store)

    async def run():
        limits = ProviderRateLimits(requests_per_minute=1)
        await quota.acquire_global("gemini:model", limits, 1)
        waiting = asyncio.Event()
        task = asyncio.create_task(quota.acquire_global("gemini:model", limits, 1, on_wait=lambda *_: waiting.set()))
        await asyncio.wait_for(waiting.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with store.connect() as db:
            assert db.execute("SELECT COUNT(*) FROM quota_request").fetchone()[0] == 1

    asyncio.run(run())


def test_native_groups_direct_generation_and_probes_share_admission(monkeypatch, tmp_path):
    store = quota.QuotaStore(tmp_path / "global.sqlite3", clock=lambda: 1000)
    monkeypatch.setattr(quota, "global_quota_store", lambda: store)
    # A direct adapter/probe and native audit models resolve to the same scope,
    # independently of API key, run ID, hierarchy and Python object identity.
    settings = SimpleNamespace(provider="Google", name="model", max_tokens=64)
    direct = SimpleNamespace(settings=settings)
    native = quota.mark_quota_scope(SimpleNamespace(), settings)
    parent = model_pacer(native, rate_limits=ProviderRateLimits())
    worker = model_pacer(native, injected=parent, rate_limits=ProviderRateLimits())
    other = model_pacer(quota.mark_quota_scope(SimpleNamespace(), SimpleNamespace(provider="Google", name="other")),
        injected=parent, rate_limits=ProviderRateLimits())
    assert parent.scope == worker.scope == quota.model_quota_scope(direct)
    assert other.scope != parent.scope

    async def run():
        await asyncio.gather(*(worker.acquire(100) for _ in range(13)))
        response = SimpleNamespace(usage_metadata={"input_tokens": 5, "output_tokens": 1, "total_tokens": 6})
        generate = AsyncMock(return_value=response)
        assert await quota.quota_generate(direct, "OK", generate) is response
        assert store.acquire(parent.scope, ProviderRateLimits(), 1)[1]["rpm"] == 60
        await other.acquire(100)
        with store.connect() as db:
            assert db.execute("SELECT SUM(tokens) FROM quota_request WHERE scope=?", (parent.scope,)).fetchone()[0] == 1306

    asyncio.run(run())


def test_access_probe_waits_for_the_same_global_window_before_contacting_provider(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from server.infrastructure.llm import gemini
    from server.main import app

    now = [1000]
    store = quota.QuotaStore(tmp_path / "probe.sqlite3", clock=lambda: now[0])
    limits = ProviderRateLimits()
    scope = quota.quota_scope("Google", "model")
    for _ in range(limits.requests_per_minute):
        store.acquire(scope, limits, 100)
    generate = AsyncMock(return_value=SimpleNamespace(text="OK", usage_metadata=SimpleNamespace(total_token_count=6)))
    monkeypatch.setattr(gemini.genai, "Client", lambda **_: SimpleNamespace(
        aio=SimpleNamespace(chats=SimpleNamespace(create=lambda **_: SimpleNamespace(send_message=generate)))))
    original_acquire = store.acquire
    observed_waits = []

    def acquire(*args):
        result = original_acquire(*args)
        if result[0] is None:
            assert generate.await_count == 0
            observed_waits.append(result[1])
            now[0] += 60
        return result

    monkeypatch.setattr(store, "acquire", acquire)
    monkeypatch.setattr(quota, "global_quota_store", lambda: store)
    with TestClient(app) as client:
        response = client.post("/api/agents/verify-access", json={
            "model": {"provider": "Google", "name": "model"}, "api_key": "offline"})
    assert response.status_code == 200 and response.json() == {"verified": True}
    assert observed_waits == [{"rpm": 60}]
    generate.assert_awaited_once()
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*), SUM(tokens) FROM quota_request").fetchone() == (1, 6)


def test_failed_and_cancelled_submitted_attempts_keep_global_reservations(monkeypatch, tmp_path):
    store = quota.QuotaStore(tmp_path / "failures.sqlite3")
    monkeypatch.setattr(quota, "global_quota_store", lambda: store)
    model = SimpleNamespace(settings=SimpleNamespace(provider="Google", name="model", max_tokens=64))

    async def run():
        with pytest.raises(RuntimeError):
            await quota.quota_generate(model, "prompt", AsyncMock(side_effect=RuntimeError("provider failed")))
        started = asyncio.Event()

        async def blocked():
            started.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(quota.quota_generate(model, "prompt", blocked))
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with store.connect() as db:
            count, tokens = db.execute("SELECT COUNT(*), SUM(tokens) FROM quota_request").fetchone()
            assert count == 2 and tokens >= 128

    asyncio.run(run())
