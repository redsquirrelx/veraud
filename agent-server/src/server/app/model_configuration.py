"""Resolve wire overrides over trusted development settings without agent registries."""

from functools import lru_cache

from pydantic import ValidationError

from server.app.errors import InvalidConfigError
from server.app.execution_config import ExecutionConfig
from server.config.dev_agents_config import load_dev_agents_config
from server.config.schemas import ModelCredentials, ModelSettings
from server.config.settings import get_server_settings


def server_api_key() -> str:
    return get_server_settings().llm_api_key


@lru_cache(maxsize=1)
def default_model_configuration() -> dict:
    """Load the process-default model map once, independent of direct-agent registration."""
    return load_dev_agents_config()


def resolve_default_model_settings(
    agent_type: str,
    config: ExecutionConfig,
) -> tuple[ModelSettings, ModelCredentials, int]:
    return resolve_model_settings(default_model_configuration(), agent_type, config)


def resolve_model_settings(
    base_config: dict,
    agent_type: str,
    config: ExecutionConfig,
    *,
    api_key_provider=server_api_key,
) -> tuple[ModelSettings, ModelCredentials, int]:
    """Merge partial request values with the selected trusted stage defaults."""
    base_settings, base_model = base_config.get(agent_type, (None, None))
    provider = config.model.provider or (
        base_model.provider if base_model else "gemini"
    )
    if (
        provider.lower() == "groq"
        and not config.model.name
        and (base_model is None or base_model.provider.lower() != "groq")
    ):
        raise InvalidConfigError("model.name is required when switching to provider 'groq'")
    name = config.model.name or (base_model.name if base_model else None)
    if not name:
        raise InvalidConfigError("model.name is required for this agent_type")
    temperature = config.model.temperature
    if temperature is None:
        temperature = base_model.temperature if base_model else 0.2
    max_tokens = config.model.max_tokens
    if max_tokens is None:
        max_tokens = base_model.max_tokens if base_model else 40000
    timeout = config.timeout_seconds
    if timeout is None:
        timeout = base_settings.timeout_seconds if base_settings else 60
    if timeout <= 0:
        raise InvalidConfigError("timeout_seconds must be positive")
    try:
        api_key = config.api_key or api_key_provider()
    except ValidationError:
        api_key = "dev-dummy-key"
    return (
        ModelSettings(
            provider=provider,
            name=name,
            temperature=temperature,
            max_tokens=max_tokens,
        ),
        ModelCredentials(api_key=api_key),
        timeout,
    )
