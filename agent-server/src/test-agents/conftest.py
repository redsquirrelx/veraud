"""Keep offline agent tests independent of the developer's launch settings."""

import pytest

from server.config import token_budget


@pytest.fixture(autouse=True)
def isolated_token_budget_policy(tmp_path, monkeypatch):
    # Missing launch settings deliberately select the finite-budget default.
    # Unlimited-mode tests can supply their own file explicitly.
    monkeypatch.setattr(token_budget, "LAUNCH_PATH", tmp_path / "test-token-policy.json")
    token_budget.token_budget_policy.cache_clear()
    yield
    token_budget.token_budget_policy.cache_clear()
