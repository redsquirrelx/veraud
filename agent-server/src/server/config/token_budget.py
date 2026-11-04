"""Process-wide cumulative-token policy, loaded from the local launch settings."""

import json
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path

from config.agents.budgets import TokenBudgetPolicy

LAUNCH_PATH = Path(__file__).resolve().parents[3] / "launch.json"
_override: ContextVar[TokenBudgetPolicy | None] = ContextVar("token_budget_policy", default=None)


@lru_cache(maxsize=1)
def token_budget_policy() -> TokenBudgetPolicy:
    """Read once per process; omitted settings use unlimited cumulative tokens."""
    values = json.loads(LAUNCH_PATH.read_text(encoding="utf-8")) if LAUNCH_PATH.is_file() else {}
    return TokenBudgetPolicy.model_validate({key: value for key, value in values.items()
        if key in TokenBudgetPolicy.model_fields})


def token_budget_exceeded(tokens: int, limit: int) -> bool:
    return not effective_token_budget_policy().unlimited_token_budget and tokens > limit


def effective_token_budget_policy() -> TokenBudgetPolicy:
    return _override.get() or token_budget_policy()


@contextmanager
def using_token_budget_policy(policy: TokenBudgetPolicy | None):
    token = _override.set(policy)
    try:
        yield
    finally:
        _override.reset(token)
