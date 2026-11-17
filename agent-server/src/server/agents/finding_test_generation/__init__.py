"""Lazy public exports keep schema imports independent of graph execution."""

from importlib import import_module

__all__ = [
    "AuditDocument",
    "Finding",
    "FindingTestGenerationAgent",
    "FindingTestGenerationRequest",
    "FindingTestGenerationResult",
    "VerificationSpec",
    "VerificationSuiteManifest",
]


def __getattr__(name: str):
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    if name == "FindingTestGenerationAgent":
        module = import_module(".agent", __name__)
    elif name in {"VerificationSpec", "VerificationSuiteManifest", "AuditDocument", "Finding",
                  "FindingTestGenerationRequest", "FindingTestGenerationResult"}:
        module = import_module(".schemas", __name__)
    else:  # pragma: no cover - defensive
        raise AttributeError(name)
    value = getattr(module, name)
    globals()[name] = value
    return value
