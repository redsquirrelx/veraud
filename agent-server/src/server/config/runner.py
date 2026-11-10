"""Standalone agent configuration with separately validated launch policy."""

import json
from pathlib import Path

from pydantic import BaseModel

from config.agents.budgets import TokenBudgetPolicy

from ..agent_services.budgeting.policy import token_budget_policy


def load_runner_config[T: BaseModel](config_type: type[T], path: str | None) -> tuple[T, TokenBudgetPolicy]:
    values = json.loads(Path(path).read_text(encoding="utf-8")) if path else {}
    if not isinstance(values, dict):
        raise TypeError("Runner configuration must be a JSON object.")
    # Only the global launch file owns the switch; agent files cannot override it.
    if path and Path(path).resolve() == Path(__file__).resolve().parents[3] / "launch.json":
        values.pop("budgets_enabled", None)
    elif "budgets_enabled" in values:
        raise ValueError("Configure budgets_enabled only in launch.json, not per agent")
    policy = token_budget_policy()
    return config_type.model_validate(values), policy
