"""Shared immutable configuration/contract semantics without runtime dependencies."""

from copy import deepcopy
from typing import Any, ClassVar, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ConfigContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    defaults: ClassVar[dict[str, Any]] = {}
    bounds: ClassVar[dict[str, dict[str, int | float]]] = {}

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs):
        """Apply data presets without redeclaring inherited fields or their validation."""
        super().__pydantic_init_subclass__(**kwargs)
        defaults = {}
        bounds = {}
        for parent in reversed(cls.__mro__):
            defaults.update(parent.__dict__.get("defaults", {}))
            for name, constraints in parent.__dict__.get("bounds", {}).items():
                bounds.setdefault(name, {}).update(constraints)
        unknown = (defaults.keys() | bounds.keys()) - cls.model_fields.keys()
        if unknown:
            raise TypeError(f"Unknown configuration defaults: {sorted(unknown)}")
        for name in defaults.keys() | bounds.keys():
            field = deepcopy(cls.model_fields[name])
            constraints = Field(**bounds.get(name, {})).metadata
            replaced = {type(constraint) for constraint in constraints}
            field.metadata = [constraint for constraint in field.metadata if type(constraint) not in replaced] + constraints
            if name in defaults:
                field.default = deepcopy(defaults[name])
                field.default_factory = None
            cls.model_fields[name] = field
        if defaults or bounds:
            cls.model_rebuild(force=True)


class RepositoryContract(ConfigContract):
    """Existing repository-protocol contract semantics, without runtime imports."""

    model_config = ConfigDict(str_strip_whitespace=True)

    @model_validator(mode="after")
    def unique_members(self) -> Self:
        for name in type(self).model_fields:
            value = getattr(self, name)
            if isinstance(value, tuple):
                identifiers = [getattr(item, "id", item) for item in value]
                if len(set(identifiers)) != len(identifiers):
                    raise ValueError(f"Duplicate members in {name}.")
        return self
