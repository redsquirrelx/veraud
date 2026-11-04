"""Validated level-specific views derived from each agent's effective runtime fields."""

from copy import deepcopy
from functools import cache
from typing import Literal

from pydantic import BaseModel, create_model

from .base import ConfigContract

ConfigLevel = Literal["user", "developer"]


def fields_for_level(config_type: type[BaseModel], level: ConfigLevel) -> frozenset[str]:
    user_fields = frozenset(getattr(config_type, "user_fields", ()))
    unknown = user_fields - config_type.model_fields.keys()
    if unknown:
        raise ValueError(f"Unknown user configuration fields: {sorted(unknown)}")
    if level == "user":
        return user_fields
    if level == "developer":
        return frozenset(config_type.model_fields) - user_fields
    raise ValueError(f"Unknown configuration level: {level}")


@cache
def settings_type(config_type: type[BaseModel], level: ConfigLevel) -> type[BaseModel]:
    """Reuse effective defaults, types and constraints, including local agent overrides."""
    fields = fields_for_level(config_type, level)
    return create_model(
        f"{config_type.__name__}{level.title()}Settings",
        __base__=ConfigContract,
        **{name: (field.annotation, deepcopy(field)) for name, field in config_type.model_fields.items() if name in fields},
    )


def apply_settings(config_type: type[BaseModel], values: dict, level: ConfigLevel, *, base=None):
    """Validate only this level's edits, then validate the complete resolved runtime config."""
    patch = settings_type(config_type, level).model_validate(values).model_dump(exclude_unset=True)
    resolved = config_type.model_validate(base.model_dump() if isinstance(base, BaseModel) else base or {})

    def merge(current, updates):
        for key, value in updates.items():
            if isinstance(value, dict) and isinstance(current.get(key), dict):
                merge(current[key], value)
            else:
                current[key] = value
        return current

    return config_type.model_validate(merge(resolved.model_dump(), patch))
