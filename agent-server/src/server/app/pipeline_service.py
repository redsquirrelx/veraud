"""Pipeline orchestration: one generic service over a registry of definitions.

`GenericPipelineService` drives any registered pipeline by name with
per-stage configs, N execution ids, and the injected tracing/callback ports.
Adding a pipeline means registering a `PipelineDefinition`, not writing a
new service.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from pydantic import BaseModel

from ..api.schemas import ExecutionConfig
from ..config.logs import get_logger
from ..infrastructure.callback.schemas import ExecutionOutcome, ExecutionProgress
from .callback_port import CallbackSink, default_callback_sink
from .execution_service import AgentExecutionService, InvalidConfigError
from .tracing_port import LangSmithTracingBackend, TracingBackend
from .usage_reporting import report_progress

logger = get_logger("pipeline-service")

# The whole pipeline gets one deadline, like the dev runner's --timeout.
DEFAULT_PIPELINE_TIMEOUT_SECONDS = 600


class UnknownPipelineError(ValueError):
    pass


class GenericReportingHooks:
    """N-stage hooks that close one backend row per stage.

    Generalizes the old two-stage logic: tracks marked-but-unclosed rows so a
    timeout fails only what is still open, and on `close_failed` the first
    unfinished stage carries the real error while later stages are marked
    Skipped instead of hanging on Waiting forever.
    """

    def __init__(
        self,
        callbacks: CallbackSink | None,
        execution_ids: dict[str, int],
        stage_order: list[str],
    ) -> None:
        self._callbacks = callbacks
        self._ids = dict(execution_ids)
        self._order = list(stage_order)
        self.open_rows: set[int] = set()
        self.completed: set[str] = set()
        self.started: set[str] = set()
        self.usage_sources: dict[int, Callable] = {}
        self.partial_results: dict[int, BaseModel] = {}

    async def on_stage_start(self, stage: str) -> None:
        if stage in self.started or stage in self.completed:
            return
        await self._mark_running(self._ids[stage])
        self.started.add(stage)

    def usage(self, execution_id: int) -> dict:
        source = self.usage_sources.get(execution_id)
        return source().model_dump() if source is not None else {}

    def register_usage(self, stage: str, source: Callable) -> None:
        self.usage_sources[self._ids[stage]] = source

    async def on_stage_progress(self, stage: str, usage: ExecutionProgress) -> None:
        await report_progress(self._callbacks, self._ids[stage], usage)

    def retain_partial(self, stage: str, result: BaseModel) -> None:
        self.partial_results[self._ids[stage]] = result

    async def on_stage_result(self, stage: str, result: BaseModel) -> None:
        await self._report(self._ids[stage], result)
        self.completed.add(stage)

    async def on_stage_skip(self, stage: str, reason: str) -> None:
        """Close a stage the graph did not run, so its row never hangs."""
        await self._report_failure(
            self._ids[stage], f"Skipped: {reason or 'stage did not run'}"
        )
        self.completed.add(stage)

    async def close_failed(self, error: str) -> None:
        """Close whatever the failure left unfinished."""
        pending = [name for name in self._order if name not in self.completed]
        for index, name in enumerate(pending):
            if index == 0:
                await self._report_failure(self._ids[name], error)
            else:
                await self._report_failure(
                    self._ids[name], f"Skipped: {pending[0]} failed ({error})"
                )

    async def fail_open(self, error: str) -> None:
        for name in self._order:
            execution_id = self._ids[name]
            if execution_id in self.open_rows:
                await self._report_failure(execution_id, error)

    async def _mark_running(self, execution_id: int) -> None:
        if self._callbacks is None:
            return
        await self._callbacks.mark_running(execution_id)
        self.open_rows.add(execution_id)

    async def _report(self, execution_id: int, result: BaseModel) -> None:
        if self._callbacks is None:
            return
        await self._callbacks.complete(
            execution_id,
            ExecutionOutcome(status="Completed", result=result.model_dump_json(), **self.usage(execution_id)),
        )
        self.open_rows.discard(execution_id)

    async def _report_failure(self, execution_id: int, error: str) -> None:
        if self._callbacks is None:
            return
        await self._callbacks.complete(
            execution_id,
            ExecutionOutcome(
                status="Failed", error=error,
                result=self.partial_results[execution_id].model_dump_json()
                if execution_id in self.partial_results else None,
                **self.usage(execution_id),
            ),
        )
        self.open_rows.discard(execution_id)


@dataclass
class PipelineDefinition:
    """How to run one registered pipeline. New pipelines add an entry here.

    The generic service only touches `name`, `stages`, and these callables:
    stage/agent names, graph hook shapes and run lifecycles live in the
    definition, never in the service. `ctx` is the definition's private
    per-run state (e.g. snapshot, budget, models) threaded from
    `build_agents` through `create_pipeline` into `run_pipeline`.
    """

    name: str
    stages: list[str]
    parse_input: Callable[[dict], Any]
    build_agents: Callable[..., Any] = field(repr=False)
    adapt_hooks: Callable[[GenericReportingHooks], Any] = field(repr=False)
    create_pipeline: Callable[[dict[str, Any], Any, dict[str, Any]], Any] = field(repr=False)
    run_pipeline: Callable[..., Any] = field(repr=False)
    agent_types: dict[str, str] | None = None

    def agent_type_for(self, stage: str) -> str:
        return (self.agent_types or {}).get(stage, stage)


def default_pipeline_registry() -> dict[str, PipelineDefinition]:
    from .project_architecture_definition import project_architecture_definition

    return {
        "project-architecture": project_architecture_definition(),
    }


class GenericPipelineService:
    """Runs any registered pipeline by name with generic stage maps."""

    def __init__(
        self,
        execution_service: AgentExecutionService | None = None,
        callbacks_factory: Callable[[], CallbackSink | None] | None = None,
        tracing_backend: TracingBackend | None = None,
        registry: dict[str, PipelineDefinition] | None = None,
    ) -> None:
        self._exec = execution_service or AgentExecutionService()
        self._callbacks_factory = callbacks_factory or _default_callbacks
        self._tracing = tracing_backend or LangSmithTracingBackend()
        self._registry = registry if registry is not None else default_pipeline_registry()

    def list_pipelines(self) -> list[str]:
        return sorted(self._registry)

    async def run(
        self,
        pipeline_name: str,
        input_data: dict,
        config: ExecutionConfig,
        stage_configs: dict[str, ExecutionConfig] | None = None,
        execution_ids: dict[str, int] | None = None,
        timeout_seconds: int = DEFAULT_PIPELINE_TIMEOUT_SECONDS,
    ) -> dict:
        """Run the named pipeline and return its stage outputs as plain dicts."""
        definition = self._registry.get(pipeline_name)
        if definition is None:
            raise UnknownPipelineError(f"Unknown pipeline: {pipeline_name!r}")

        parsed = definition.parse_input(input_data)

        if execution_ids is not None:
            missing = [stage for stage in definition.stages if stage not in execution_ids]
            if missing:
                raise InvalidConfigError(
                    f"Missing execution ids for stages: {', '.join(missing)}"
                )

        agents, ctx = await definition.build_agents(
            self._exec, config, stage_configs, parsed, timeout_seconds
        )

        callbacks = self._callbacks_factory() if execution_ids is not None else None
        if execution_ids is not None and callbacks is None:
            logger.warning(
                "execution_ids given but no backend url is configured, "
                "so progress cannot be reported"
            )

        hooks: GenericReportingHooks | None = None
        graph_hooks: Any = None
        if execution_ids is not None:
            hooks = GenericReportingHooks(callbacks, execution_ids, definition.stages)
            graph_hooks = definition.adapt_hooks(hooks)

        pipeline = definition.create_pipeline(agents, graph_hooks, ctx)

        try:
            return await self._tracing.wrap_pipeline(
                asyncio.wait_for(
                    definition.run_pipeline(pipeline, parsed, ctx),
                    timeout_seconds,
                ),
                name=pipeline_name,
                timeout_seconds=timeout_seconds,
            )
        except TimeoutError:
            logger.error("Pipeline %r timed out after %ss", pipeline_name, timeout_seconds)
            if hooks is not None:
                await hooks.fail_open(f"Pipeline timed out after {timeout_seconds}s")
            raise
        except Exception as error:
            if hooks is not None:
                await hooks.close_failed(str(error) or type(error).__name__)
            raise
        finally:
            if callbacks is not None:
                await callbacks.aclose()


def _default_callbacks() -> CallbackSink | None:
    return default_callback_sink()


@lru_cache(maxsize=1)
def get_generic_pipeline_service() -> GenericPipelineService:
    return GenericPipelineService()
