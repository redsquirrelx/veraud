"""Lazy public exports keep schema-only imports independent of agent execution."""

from importlib import import_module

__all__ = ["MaintainabilityConfig", "MaintainabilityManagerAgent", "MaintainabilityReport", "MaintainabilityRequest"]


def __getattr__(name: str):
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(".agent" if name == "MaintainabilityManagerAgent" else ".schemas", __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value
