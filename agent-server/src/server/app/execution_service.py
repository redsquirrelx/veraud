import asyncio
from functools import lru_cache

from pydantic import ValidationError

from ..agents.base import BaseAgent
from ..agents.dummy.agent import DummyAgent
from ..agents.dummy.schemas import DummyInput
from ..agents.models.base import Model
from ..agents.models.gemini import GeminiModel
from ..agents.models.openrouter import OpenRouterModel
from ..api.schemas import ExecutionConfig
from ..config.dev_agents_config import load_dev_agents_config
from ..config.logs import get_logger
from ..config.schemas import (
    AgentSettings,
    ModelCredentials,
    ModelSettings,
)
from .agent_registry import AgentRegistry

logger = get_logger("execution-service")


class InvalidConfigError(ValueError):
    pass


def build_model(settings: ModelSettings, credentials: ModelCredentials) -> Model:
    provider = settings.provider.lower()

    logger.info("Building model provider=%r name=%r", provider, settings.name)

    if provider in ("gemini", "google"):
        return GeminiModel(settings=settings, credentials=credentials)
    
    if provider in ("openrouter", "openai"):
        return OpenRouterModel(settings=settings, credentials=credentials)
    
    raise InvalidConfigError(f"Unsupported model provider: {settings.provider!r}")


def build_default_registry() -> AgentRegistry:
    registry = AgentRegistry()
    
    registry.register(DummyAgent.agent_type, DummyAgent)

    return registry


class AgentExecutionService:
    """Stateless manager: instantiates the agent matching agent_type,
    assigns it the base config from dev_agents_config (overridden by the
    request), and runs it."""

    def __init__(self, registry: AgentRegistry | None = None) -> None:
        self._registry = registry or build_default_registry()
        self._base_config = load_dev_agents_config()

    def list_agents(self) -> list[str]:
        return self._registry.list_agents()

    def build_agent(
        self, agent_type: str, config: ExecutionConfig
    ) -> tuple[BaseAgent, int]:
        logger.info("Instantiating agent %r", agent_type)
        agent_cls = self._registry.get(agent_type)

        base_settings, base_model = self._base_config.get(agent_type, (None, None))

        provider = config.model.provider or (
            base_model.provider if base_model else "gemini"
        )

        name = config.model.name or (base_model.name if base_model else None)
        
        if not name:
            raise InvalidConfigError("model.name is required for this agent_type")
        
        temperature = config.model.temperature
        if temperature is None:
            temperature = base_model.temperature if base_model else 0.2

        max_tokens = config.model.max_tokens
        if max_tokens is None:
            max_tokens = base_model.max_tokens if base_model else 1000

        timeout = config.timeout_seconds
        if timeout is None:
            timeout = (
                base_settings.timeout_seconds if base_settings else 60
            )
        if timeout <= 0:
            raise InvalidConfigError("timeout_seconds must be positive")

        try:
            api_key = config.api_key or self._server_api_key()
        except ValidationError:
            api_key = "dev-dummy-key"

        model = build_model(
            ModelSettings(
                provider=provider,
                name=name,
                temperature=temperature,
                max_tokens=max_tokens,
            ),
            ModelCredentials(api_key=api_key),
        )

        agent = agent_cls(
            settings=AgentSettings(agent_id=agent_type, timeout_seconds=timeout),
            model=model,
        )

        logger.info(
            "Instantiated agent %r model=%r timeout=%ss",
            agent_type, name, timeout,
        )

        return agent, timeout

    @staticmethod
    def _server_api_key() -> str:
        from ..config.settings import settings as app_settings

        return app_settings.llm_api_key

    async def run(
        self,
        agent_type: str,
        config: ExecutionConfig,
        payload: DummyInput | dict,
    ):
        agent, timeout = self.build_agent(agent_type, config)

        if isinstance(payload, dict):
            payload = DummyInput(**payload)

        logger.info("Running agent %r (timeout=%ss)", agent_type, timeout)

        try:
            result = await asyncio.wait_for(agent.run(payload), timeout)
        except TimeoutError:
            logger.error("Agent %r timed out after %ss", agent_type, timeout)
            raise

        logger.info("Agent %r finished", agent_type)
        
        return result


@lru_cache(maxsize=1)
def get_execution_service() -> AgentExecutionService:
    return AgentExecutionService()
