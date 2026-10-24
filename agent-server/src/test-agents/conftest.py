"""Keep offline agent tests independent of the developer's launch settings."""

import pytest

from server.config import token_budget


@pytest.fixture(autouse=True)
def isolated_token_budget_policy(tmp_path, monkeypatch):
    # Budget-limit regressions explicitly select finite mode, independently of
    # the unlimited production default and the developer's launch settings.
    path = tmp_path / "test-token-policy.json"
    path.write_text('{"unlimited_token_budget": false}', encoding="utf-8")
    monkeypatch.setattr(token_budget, "LAUNCH_PATH", path)
    token_budget.token_budget_policy.cache_clear()
    yield
    token_budget.token_budget_policy.cache_clear()
