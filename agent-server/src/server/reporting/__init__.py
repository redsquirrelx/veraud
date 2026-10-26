"""Lazy report agent exports; importing schemas does not initialize LangGraph."""

__all__ = ["AuditReportAgent", "AuditReportRequest", "SoftwareAuditReport"]


def __getattr__(name: str):
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name = ".agent" if name == "AuditReportAgent" else ".schemas"
    from importlib import import_module

    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value
