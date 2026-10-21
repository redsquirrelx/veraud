"""Model-selection validation for the implemented maintainability hierarchy."""

from ..agents.maintainability.manager.registry import COORDINATORS
from ..agents.maintainability.modularity.coordinator.registry import (
    INVESTIGATORS as MODULARITY_INVESTIGATORS,
)
from ..agents.maintainability.reusability.coordinator.registry import (
    INVESTIGATORS as REUSABILITY_INVESTIGATORS,
)
from .execution_service import InvalidConfigError

MAINTAINABILITY_AGENT_TYPES = (
    "maintainability_manager", *COORDINATORS, *MODULARITY_INVESTIGATORS, *REUSABILITY_INVESTIGATORS,
)


def validate_model_configs(configs, attribute="maintainability"):
    if configs is None:
        return
    attributes = [attribute] if isinstance(attribute, str) else attribute
    required = (*(MAINTAINABILITY_AGENT_TYPES if "maintainability" in attributes else ()),
        *(("security",) if "security" in attributes else ()),
        *(("functional_adequacy",) if "functional_adequacy" in attributes else ()))
    if set(configs) != set(required):
        raise InvalidConfigError(f"agent_configs must configure every {attribute} agent exactly once: "
            + ", ".join(required))
    if any(not value.model.provider or not value.model.name or not value.api_key
           or value.timeout_seconds is not None for value in configs.values()):
        raise InvalidConfigError("Each agent configuration requires model.provider, model.name and api_key; "
            "execution timeout belongs to the audit configuration.")
