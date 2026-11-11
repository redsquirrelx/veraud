"""Model-selection validation for the implemented maintainability hierarchy."""

from ..agents.maintainability.v2.manager.registry import registered_coordinators
from ..agents.maintainability.v2.modularity.coordinator.registry import (
    registered_investigators as modularity_investigators,
)
from ..agents.maintainability.v2.reusability.coordinator.registry import (
    registered_investigators as reusability_investigators,
)
from .errors import InvalidConfigError

MAINTAINABILITY_AGENT_TYPES = (
    "maintainability_manager", *registered_coordinators(),
    *modularity_investigators(), *reusability_investigators(),
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
