"""Standalone agent configuration with separately validated launch policy."""

import json
from pathlib import Path

from pydantic import BaseModel

from config.agents.budgets import TokenBudgetPolicy

from .token_budget import token_budget_policy


def load_runner_config[T: BaseModel](config_type: type[T], path: str | None) -> tuple[T, TokenBudgetPolicy]:
    values = json.loads(Path(path).read_text(encoding="utf-8")) if path else {}
    if not isinstance(values, dict):
        raise TypeError("Runner configuration must be a JSON object.")
    policy_values = {key: values.pop(key) for key in TokenBudgetPolicy.model_fields if key in values}
    policy = TokenBudgetPolicy.model_validate({**token_budget_policy().model_dump(), **policy_values})
    return config_type.model_validate(values), policy
