"""Keep offline agent tests independent of the developer's launch settings."""

import pytest

from server.config import token_budget


@pytest.fixture(autouse=True)
def isolated_token_budget_policy(tmp_path, monkeypatch):
    # Budget regressions use finite global mode independently of launch settings.
    path = tmp_path / "test-token-policy.json"
    path.write_text('{"budgets_enabled": true}', encoding="utf-8")
    monkeypatch.setattr(token_budget, "LAUNCH_PATH", path)
    token_budget.token_budget_policy.cache_clear()
    yield
    token_budget.token_budget_policy.cache_clear()
