"""Provider tests must never consume the application's persistent quota window."""

import pytest


@pytest.fixture
def finite_token_budget(monkeypatch):
    """Budget-exhaustion regressions explicitly opt out of the unlimited default."""
    from server.config import token_budget

    monkeypatch.setattr(token_budget, "token_budget_policy", lambda: token_budget.TokenBudgetPolicy(unlimited_token_budget=False))


@pytest.fixture(autouse=True)
def isolated_global_provider_quotas(tmp_path, monkeypatch):
    from server.infrastructure.llm import quota

    store = None

    def isolated_store():
        nonlocal store
        if store is None:
            store = quota.QuotaStore(tmp_path / "provider-quotas.sqlite3")
        return store

    monkeypatch.setattr(quota, "global_quota_store", isolated_store)
    # The pacing module also imports the store factory for settlement.
    from server.runtimes.investigation import provider

    monkeypatch.setattr(provider, "global_quota_store", isolated_store)
