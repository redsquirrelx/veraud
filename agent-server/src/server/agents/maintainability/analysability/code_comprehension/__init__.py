"""Lazy exports, without constructing models or repository resources."""

from importlib import import_module

__all__ = ["CodeComprehensionAgent", "CodeComprehensionConfig", "CodeComprehensionRequest", "CodeComprehensionResult"]


def __getattr__(name: str):
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    suffix = ".agent" if name.endswith("Agent") else ".config" if name.endswith("Config") else ".schemas"
    value = getattr(import_module(suffix, __name__), name)
    globals()[name] = value
    return value
