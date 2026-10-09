import asyncio
from functools import lru_cache

from pydantic import BaseModel, ValidationError

from ..agents.analyzer.agent import ProjectAnalyzerAgent
from ..agents.base import BaseAgent
from ..agents.dummy.agent import DummyAgent
from ..agents.models.base import Model
from ..agents.models.gemini import GeminiModel
from ..agents.models.openrouter import OpenRouterModel
from ..api.schemas import ExecutionConfig
from ..config import tracing
from ..config.dev_agents_config import load_dev_agents_config
from ..config.logs import get_logger
from ..config.schemas import (
    AgentSettings,
    ModelCredentials,
    ModelSettings,
)
from ..infrastructure.callback.client import CallbackClient
from ..infrastructure.callback.schemas import CallbackConfig, ExecutionOutcome
from .agent_registry import AgentRegistry

logger = get_logger("execution-service")


class InvalidConfigError(ValueError):
    pass


class InvalidInputError(ValueError):
    pass


def _backend_url() -> str | None:
    """Where to report progress, from PORT_BACKEND, or None if unavailable.

    Imported here rather than at module level so that everything in this package
    still imports when there is no .env, which the dev runners rely on.
    """
    try:
        from ..config.settings import get_server_settings

        settings = get_server_settings()
    except ValidationError:
        return None

    return f"http://localhost:{settings.port_backend}"


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
    registry.register(ProjectAnalyzerAgent.agent_type, ProjectAnalyzerAgent)

    return registry


class AgentExecutionService:
    """Stateless manager: instantiates the agent matching agent_type,
    assigns it the base config from dev_agents_config (overridden by the
    request), and runs it."""

    def __init__(self, registry: AgentRegistry | None = None) -> None:
        self._registry = registry or build_default_registry()
        self._base_config = load_dev_agents_config()

        # Before any agent runs, so the LangSmith flags are in place by the
        # time the first graph builds its tracer.
        tracing.setup()

    def list_agents(self) -> list[str]:
        return self._registry.list_agents()

    def describe_agent(self, agent_type: str) -> dict:
        """What an agent accepts and returns, read from its own schemas.

        The agent owns its contract, so a new agent needs no change here.
        """
        agent_cls = self._registry.get(agent_type)
        return {
            "agent_type": agent_type,
            "input_schema": agent_cls.input_schema.model_json_schema(),
            "output_schema": agent_cls.output_schema.model_json_schema(),
        }

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
        from ..config.settings import get_server_settings

        return get_server_settings().llm_api_key

    async def run(
        self,
        agent_type: str,
        config: ExecutionConfig,
        payload: dict,
        execution_id: int | None = None,
    ) -> BaseModel:
        """Validate the payload against the agent's own input schema, then run it.

        Returns the agent's output model instance. The HTTP layer serialises it.

        When `execution_id` is given, the run reports its own progress back to the
        backend that created that row: once when it starts and once when it ends.
        The agent itself knows nothing about this, so no agent has to change to
        take part.
        """
        agent, timeout = self.build_agent(agent_type, config)

        input_schema = type(agent).input_schema
        try:
            agent_input = input_schema.model_validate(payload)
        except ValidationError as error:
            raise InvalidInputError(
                f"Invalid input for agent {agent_type!r}: {error}"
            ) from None

        logger.info(
            "Running agent %r (timeout=%ss input=%s execution=%s)",
            agent_type, timeout, type(agent_input).__name__, execution_id,
        )

        callbacks = self._callbacks(execution_id)

        try:
            await self._mark_running(callbacks, execution_id)

            result = await tracing.traced_agent_run(
                asyncio.wait_for(agent.run(agent_input), timeout),
                name=agent_type,
                model=agent.model.settings.name,
                timeout_seconds=timeout,
            )

            await self._report(callbacks, execution_id, result)

            return result

        except TimeoutError:
            logger.error("Agent %r timed out after %ss", agent_type, timeout)
            await self._report_failure(callbacks, execution_id, f"Agent timed out after {timeout}s")
            raise
        except Exception as error:
            await self._report_failure(callbacks, execution_id, str(error))
            raise
        finally:
            if callbacks is not None:
                await callbacks.aclose()

    @staticmethod
    def _callbacks(execution_id: int | None) -> CallbackClient | None:
        """A client for reporting this run, or None when nobody asked for one."""
        if execution_id is None:
            return None

        backend_url = _backend_url()
        if backend_url is None:
            logger.warning(
                "execution_id=%s given but no backend url is configured, "
                "so progress cannot be reported",
                execution_id,
            )
            return None

        return CallbackClient(CallbackConfig(backend_url=backend_url))

    async def _mark_running(
        self, callbacks: CallbackClient | None, execution_id: int | None
    ) -> None:
        if callbacks is None or execution_id is None:
            return

        await callbacks.mark_running(execution_id)

    async def _report(
        self,
        callbacks: CallbackClient | None,
        execution_id: int | None,
        result: BaseModel,
    ) -> None:
        """Close the row with the agent's output, serialized.

        The backend stores `result` as an opaque string, so it is JSON here rather
        than a nested object.
        """
        if callbacks is None or execution_id is None:
            return

        await callbacks.complete(
            execution_id,
            ExecutionOutcome(status="Completed", result=result.model_dump_json()),
        )

    async def _report_failure(
        self,
        callbacks: CallbackClient | None,
        execution_id: int | None,
        error: str,
    ) -> None:
        if callbacks is None or execution_id is None:
            return

        await callbacks.complete(
            execution_id,
            ExecutionOutcome(status="Failed", error=error),
        )


@lru_cache(maxsize=1)
def get_execution_service() -> AgentExecutionService:
    return AgentExecutionService()
