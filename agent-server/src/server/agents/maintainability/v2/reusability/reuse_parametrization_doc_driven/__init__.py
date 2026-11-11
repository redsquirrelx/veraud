"""Lazy public exports keep schema imports independent of graph execution."""

from importlib import import_module

__all__ = [
    "DocumentClaimRecord",
    "ParametrizationCandidate",
    "ParametrizationPlanSelection",
    "ReuseParametrizationConfig",
    "ReuseParametrizationDocDrivenAgent",
    "ReuseParametrizationDocDrivenRequest",
    "ReuseParametrizationDocDrivenResult",
]


def __getattr__(name: str):
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    api = "config" if name.endswith("Config") else "agent" if name.endswith("Agent") else "schemas"
    module = import_module(f".{api}", __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value
