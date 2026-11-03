import asyncio
from collections.abc import Callable
from contextlib import AsyncExitStack
from functools import lru_cache
from typing import TYPE_CHECKING

from pydantic import BaseModel, ValidationError

from config.agents.budgets import ExecutionTimingConfig
from server.app.errors import InvalidConfigError, InvalidInputError
from server.app.execution_config import ExecutionConfig
from server.app.model_configuration import (
    default_model_configuration,
    resolve_model_settings,
    server_api_key,
)
from server.examples.dummy.agent import DummyAgent
from server.infrastructure.llm.factory import UnsupportedModelProviderError
from server.infrastructure.llm.factory import build_model as _build_model
from server.infrastructure.llm.resources import close_model_clients
from server.infrastructure.tracing import LangSmithTracingBackend, TracingBackend
from server.runtimes.direct import BaseAgent
from server.services.execution_error_details import (
    capture_execution_errors,
    exception_error_detail,
    result_error_detail,
)

from ..agents.functional_adequacy.agent import FunctionalAdequacyAgent
from ..config import tracing
from ..config.logs import get_logger
from ..config.schemas import (
    AgentSettings,
    ModelCredentials,
    ModelSettings,
)
from ..infrastructure.callback.schemas import ExecutionOutcome
from ..infrastructure.llm.base import Model
from ..runtimes.repository.timing import ActiveDeadline, within_deadline
from .agent_registry import AgentRegistry
from .callback_port import (
    CallbackSink,
    backend_url,
    default_callback_sink,
)
from .usage_reporting import ReportingModel

logger = get_logger("execution-service")

if TYPE_CHECKING:
    from ..blackboard.interface import Blackboard


def _backend_url() -> str | None:
    """Where to report progress, from PORT_BACKEND, or None if unavailable.

    Kept here for backwards compatibility; new code should import
    `backend_url` from `.callback_port`.
    """
    return backend_url()


def build_model(settings: ModelSettings, credentials: ModelCredentials) -> Model:
    try:
        return _build_model(settings, credentials)
    except UnsupportedModelProviderError as error:
        raise InvalidConfigError(str(error)) from None


async def close_model_client(model) -> None:
    """Close a direct-run provider client within the shared cleanup grace."""
    deadline = ActiveDeadline(
        ExecutionTimingConfig().cancellation_grace_seconds,
        cancellation_grace_seconds=0,
        label="direct_provider_cleanup",
    )
    try:
        await within_deadline(close_model_clients(model), deadline)
    except TimeoutError:
        logger.warning("direct_provider_cleanup_timeout")


def build_default_registry() -> AgentRegistry:
    registry = AgentRegistry()

    registry.register(DummyAgent.agent_type, DummyAgent)
    registry.register(
        FunctionalAdequacyAgent.agent_type, FunctionalAdequacyAgent
    )

    return registry


class AgentExecutionService:
    """Stateless manager: instantiates the agent matching agent_type,
    assigns it the base config from dev_agents_config (overridden by the
    request), and runs it.

    `tracing` and `callbacks_factory` are injectable ports (Phase 1): production
    uses the LangSmith backend and the HTTP backend sink; tests inject
    recorders or no-ops. Defaults preserve the previous behaviour.
    """

    def __init__(
        self,
        registry: AgentRegistry | None = None,
        tracing_backend: TracingBackend | None = None,
        callbacks_factory: Callable[[], CallbackSink | None] | None = None,
    ) -> None:
        self._registry = registry or build_default_registry()
        self._base_config = dict(default_model_configuration())
        self._tracing = tracing_backend or LangSmithTracingBackend()
        self._callbacks_factory = callbacks_factory or default_callback_sink

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

    def resolve_model_settings(
        self, agent_type: str, config: ExecutionConfig
    ) -> tuple[ModelSettings, ModelCredentials, int]:
        """Merge request overrides over server defaults for one stage.

        Shared by `build_agent` and pipeline definitions whose agents are not
        `BaseAgent`s (e.g. project-architecture stages): the merge, the groq
        name guard and the dev-key fallback live here exactly once.
        """
        return resolve_model_settings(
            self._base_config,
            agent_type,
            config,
            api_key_provider=self._server_api_key,
        )

    def build_agent(
        self,
        agent_type: str,
        config: ExecutionConfig,
        resource_stack: AsyncExitStack | None = None,
    ) -> tuple[BaseAgent, int]:
        logger.info("Instantiating agent %r", agent_type)
        agent_cls = self._registry.get(agent_type)

        settings, credentials, timeout = self.resolve_model_settings(agent_type, config)

        model = build_model(settings, credentials)
        if resource_stack is not None:
            resource_stack.push_async_callback(close_model_client, model)

        agent = agent_cls(
            settings=AgentSettings(agent_id=agent_type, timeout_seconds=timeout),
            model=model,
        )

        logger.info(
            "Instantiated agent %r model=%r timeout=%ss",
            agent_type, settings.name, timeout,
        )

        return agent, timeout

    @staticmethod
    def _server_api_key() -> str:
        return server_api_key()

    async def run(
        self,
        agent_type: str,
        config: ExecutionConfig,
        payload: dict,
        execution_id: int | None = None,
        *,
        blackboard: "Blackboard | None" = None,
    ) -> BaseModel:
        """Validate the payload against the agent's own input schema, then run it.

        Returns the agent's output model instance. The HTTP layer serialises it.

        When `execution_id` is given, the run reports its own progress back to the
        backend that created that row: once when it starts and once when it ends.
        The agent itself knows nothing about this, so no agent has to change to
        take part.
        """
        resources = AsyncExitStack()
        await resources.__aenter__()
        try:
            agent, timeout = self.build_agent(agent_type, config, resources)
            return await self._run_built_agent(
                agent, timeout, agent_type, payload, execution_id, blackboard
            )
        finally:
            await resources.aclose()


    async def _run_built_agent(
        self, agent, timeout, agent_type, payload, execution_id, blackboard
    ) -> BaseModel:
        agent.blackboard = blackboard

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
        reporting_model = ReportingModel(agent.model, callbacks, execution_id)
        agent.model = reporting_model

        try:
            await self._mark_running(callbacks, execution_id)

            with capture_execution_errors() as incidents:
                result = await self._tracing.wrap_stage(
                    asyncio.wait_for(agent.run(agent_input), timeout),
                    name=agent_type,
                    model=agent.model.settings.name,
                    timeout_seconds=timeout,
                )

            detail = result_error_detail(result, agent_id=agent_type, children=incidents)
            await self._report(callbacks, execution_id, result, reporting_model.usage.model_dump(), detail)

            return result

        except TimeoutError as error:
            logger.error("Agent %r timed out after %ss", agent_type, timeout)
            detail = exception_error_detail(error, agent_id=agent_type)
            await self._report_failure(callbacks, execution_id, f"Agent timed out after {timeout}s", reporting_model.usage.model_dump(), detail)
            raise
        except Exception as error:  # noqa: BLE001 - Report failures without leaking provider credentials.
            message = f"Agent execution failed ({type(error).__name__}); check model access and agent input"
            detail = exception_error_detail(error, agent_id=agent_type)
            await self._report_failure(callbacks, execution_id, message, reporting_model.usage.model_dump(), detail)
            raise InvalidConfigError(message) from None
        finally:
            if callbacks is not None:
                await callbacks.aclose()

    def _callbacks(self, execution_id: int | None) -> CallbackSink | None:
        """A sink for reporting this run, or None when nobody asked for one."""
        if execution_id is None:
            return None

        callbacks = self._callbacks_factory()
        if callbacks is None:
            logger.warning(
                "execution_id=%s given but no backend url is configured, "
                "so progress cannot be reported",
                execution_id,
            )
            return None

        return callbacks

    async def _mark_running(
        self, callbacks: CallbackSink | None, execution_id: int | None
    ) -> None:
        if callbacks is None or execution_id is None:
            return

        await callbacks.mark_running(execution_id)

    async def _report(
        self,
        callbacks: CallbackSink | None,
        execution_id: int | None,
        result: BaseModel,
        usage: dict | None = None,
        error_detail=None,
    ) -> None:
        """Close the row with the agent's output, serialized.

        The backend stores `result` as an opaque string, so it is JSON here rather
        than a nested object.
        """
        if callbacks is None or execution_id is None:
            return

        await callbacks.complete(
            execution_id,
            ExecutionOutcome(status="Completed", result=result.model_dump_json(), error_detail=error_detail, **(usage or {})),
        )

    async def _report_failure(
        self,
        callbacks: CallbackSink | None,
        execution_id: int | None,
        error: str,
        usage: dict | None = None,
        error_detail=None,
    ) -> None:
        if callbacks is None or execution_id is None:
            return

        await callbacks.complete(
            execution_id,
            ExecutionOutcome(status="Failed", error=error, error_detail=error_detail, **(usage or {})),
        )


@lru_cache(maxsize=1)
def get_execution_service() -> AgentExecutionService:
    return AgentExecutionService()
