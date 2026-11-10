"""One process-wide switch; never overridden by an agent or invocation context."""

import json
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from config.agents.budgets import BudgetPolicy

LAUNCH_PATH = Path(__file__).resolve().parents[4] / "launch.json"
TokenBudgetPolicy = BudgetPolicy


@lru_cache(maxsize=1)
def token_budget_policy() -> BudgetPolicy:
    """Read the global launch policy once. Restart after changing the switch."""
    values = json.loads(LAUNCH_PATH.read_text(encoding="utf-8")) if LAUNCH_PATH.is_file() else {}
    if "unlimited_token_budget" in values:
        raise ValueError("Replace unlimited_token_budget with the global budgets_enabled switch in launch.json")
    return BudgetPolicy.model_validate({"budgets_enabled": values.get("budgets_enabled", True)})


def effective_token_budget_policy():
    return token_budget_policy()


load_budget_policy = token_budget_policy


def budgets_enabled():
    return token_budget_policy().budgets_enabled


def exceeds(value, limit):
    return budgets_enabled() and value > limit


token_budget_exceeded = exceeds


def timeout_seconds(seconds):
    """asyncio/transport timeout: None means no execution budget deadline."""
    return seconds if budgets_enabled() else None


async def wait_for(awaitable, timeout):
    """Execution timeout only; not for pacing, quota waits or cleanup guards."""
    import asyncio

    return await asyncio.wait_for(awaitable, timeout_seconds(timeout))


@contextmanager
def using_token_budget_policy(policy):
    """Legacy runners may pass the global policy, but cannot override it."""
    if policy is not None and policy != token_budget_policy():
        raise ValueError("Per-agent budget overrides are unsupported; configure launch.json budgets_enabled")
    yield
