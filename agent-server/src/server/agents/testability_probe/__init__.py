"""TestabilityProbeAgent: generates portable, executable verification suites
from testability-investigation findings (TestIsolationAgent /
TestControllabilityAgent). It authors pytest modules via an LLM, validates
them in a disposable workspace, and packages a `.tallercito/` ZIP that can be
re-run on later commits without any LLM.
"""

from importlib import import_module

_LAZY = {
    "TestabilityProbeAgent": "agent",
    "ProbeRequest": "schemas",
    "ProbeResult": "schemas",
    "VerificationResult": "schemas",
    "ValidationRecord": "schemas",
}

__all__ = list(_LAZY)


def __getattr__(name: str):
    module_name = _LAZY.get(name)
    if module_name is None:
        raise AttributeError(name)
    module = import_module(f".{module_name}", __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value
