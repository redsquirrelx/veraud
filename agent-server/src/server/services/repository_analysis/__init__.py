"""Lazy exports for deterministic repository analysis and evidence queries."""

from importlib import import_module

_EXPORTS = {
    "RepositoryQueryService": ".queries",
    "RepositoryAnalysisInput": ".schemas",
    "RepositorySnapshot": ".schemas",
    "RepositoryAnalysisService": ".service",
}
__all__ = list(_EXPORTS)


def __getattr__(name: str):
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module, __name__), name)
    globals()[name] = value
    return value
