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


def validate_model_configs(configs):
    if configs is None:
        return
    if set(configs) != set(MAINTAINABILITY_AGENT_TYPES):
        raise InvalidConfigError("agent_configs must configure every maintainability agent exactly once: "
            + ", ".join(MAINTAINABILITY_AGENT_TYPES))
    if any(not value.model.provider or not value.model.name or not value.api_key
           or value.timeout_seconds is not None for value in configs.values()):
        raise InvalidConfigError("Each agent configuration requires model.provider, model.name and api_key; "
            "execution timeout belongs to the audit configuration.")
