"""Pipeline orchestration: one generic service plus a legacy facade.

Phase 2: `GenericPipelineService` drives any registered pipeline by name with
per-stage configs, N execution ids, and the injected tracing/callback ports.
Adding a pipeline means registering a definition, not writing a new service.

`ArchitectureAuditService` stays as a typed facade over the generic path so
`POST /api/pipelines/architecture-audit/run` behaves exactly as before.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from ..agents.analyzer.schemas import ProjectDescription
from ..agents.architect.schemas import ArchitectureDescription
from ..api.schemas import ExecutionConfig
from ..config.logs import get_logger
from ..infrastructure.callback.schemas import ExecutionOutcome
from ..pipelines.architecture_audit import ArchitectureAuditPipeline
from .callback_port import CallbackSink, default_callback_sink
from .execution_service import AgentExecutionService, InvalidConfigError
from .tracing_port import LangSmithTracingBackend, TracingBackend

logger = get_logger("pipeline-service")

# The whole pipeline gets one deadline, like the dev runner's --timeout.
DEFAULT_PIPELINE_TIMEOUT_SECONDS = 600


class PipelineExecutionIds(BaseModel):
    """Rows the backend created for this pipeline run."""

    analyzer: int = Field(ge=1)
    architect: int = Field(ge=1)


class PipelineStageConfigs(BaseModel):
    """Explicit backend configuration for each independently configured stage."""

    analyzer: ExecutionConfig
    architect: ExecutionConfig


class PipelineInput(BaseModel):
    """Where to look. The architect's input is derived from the analyzer's
    output mid-run, so the caller only ever sends the repository root."""

    root_path: str = Field(description="Repository root to audit")
    max_files: int = Field(default=500, ge=1)
    max_depth: int = Field(default=8, ge=1)
    max_read_rounds: int = Field(default=3, ge=0)
    max_files_per_round: int = Field(default=8, ge=1)


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

    async def on_stage_start(self, stage: str) -> None:
        await self._mark_running(self._ids[stage])

    async def on_stage_result(self, stage: str, result: BaseModel) -> None:
        await self._report(self._ids[stage], result)
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
            ExecutionOutcome(status="Completed", result=result.model_dump_json()),
        )
        self.open_rows.discard(execution_id)

    async def _report_failure(self, execution_id: int, error: str) -> None:
        if self._callbacks is None:
            return
        await self._callbacks.complete(
            execution_id,
            ExecutionOutcome(status="Failed", error=error),
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


class _ArchitectureAuditHooksAdapter:
    """Audit-specific hooks shape (`AuditHooks`) over generic stage hooks.

    Lives with the architecture-audit definition: the analyzer/architect
    method names belong to that graph, not to the generic service.
    """

    def __init__(self, generic: GenericReportingHooks) -> None:
        self._generic = generic

    async def on_analyzer_start(self) -> None:
        await self._generic.on_stage_start("analyzer")

    async def on_analysis(self, analysis: ProjectDescription) -> None:
        await self._generic.on_stage_result("analyzer", analysis)

    async def on_architect_start(self) -> None:
        await self._generic.on_stage_start("architect")

    async def on_description(self, description: ArchitectureDescription) -> None:
        await self._generic.on_stage_result("architect", description)

    async def close_failed(self, error: str) -> None:
        await self._generic.close_failed(error)

    async def fail_open(self, error: str) -> None:
        await self._generic.fail_open(error)


class _ReportingHooks:
    """Legacy audit-specific hooks, kept for backwards compatibility.

    Delegates to `GenericReportingHooks` so there is a single failure-handling
    implementation. Attribute shapes (`open_rows`, `analysis_done`) match the
    previous version. New code should use `GenericReportingHooks` directly.
    """

    def __init__(
        self,
        callbacks: CallbackSink | None,
        execution_ids: PipelineExecutionIds,
    ) -> None:
        self._generic = GenericReportingHooks(
            callbacks,
            {"analyzer": execution_ids.analyzer, "architect": execution_ids.architect},
            ["analyzer", "architect"],
        )
        self._ids = execution_ids

    @property
    def open_rows(self) -> set[int]:
        return self._generic.open_rows

    @property
    def analysis_done(self) -> bool:
        return "analyzer" in self._generic.completed

    async def on_analyzer_start(self) -> None:
        await self._generic.on_stage_start("analyzer")

    async def on_analysis(self, analysis: ProjectDescription) -> None:
        await self._generic.on_stage_result("analyzer", analysis)

    async def on_architect_start(self) -> None:
        await self._generic.on_stage_start("architect")

    async def on_description(self, description: ArchitectureDescription) -> None:
        await self._generic.on_stage_result("architect", description)

    async def close_failed(self, error: str) -> None:
        await self._generic.close_failed(error)

    async def fail_open(self, error: str) -> None:
        await self._generic.fail_open(error)


def _parse_audit_input(raw: dict) -> PipelineInput:
    try:
        return PipelineInput.model_validate(raw)
    except ValidationError as error:
        raise InvalidConfigError(f"Invalid pipeline input: {error}") from None


async def _build_audit_agents(
    exec_service: AgentExecutionService,
    config: ExecutionConfig,
    stage_configs: dict[str, ExecutionConfig] | None,
    parsed: PipelineInput,
    timeout_seconds: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    agents: dict[str, Any] = {}
    for stage in ("analyzer", "architect"):
        stage_config = (stage_configs or {}).get(stage) or config
        agent, _ = exec_service.build_agent(stage, stage_config)
        agents[stage] = agent
    return agents, {}


def _create_audit_pipeline(
    agents: dict[str, Any], graph_hooks: Any, ctx: dict[str, Any]
) -> ArchitectureAuditPipeline:
    return ArchitectureAuditPipeline(
        agents["analyzer"], agents["architect"], hooks=graph_hooks
    )


async def _run_audit_graph(
    pipeline: ArchitectureAuditPipeline, parsed: PipelineInput, ctx: dict[str, Any]
) -> dict:
    return await pipeline.run(
        parsed.root_path,
        max_files=parsed.max_files,
        max_depth=parsed.max_depth,
        max_read_rounds=parsed.max_read_rounds,
        max_files_per_round=parsed.max_files_per_round,
    )


def default_pipeline_registry() -> dict[str, PipelineDefinition]:
    from .project_architecture_definition import project_architecture_definition

    return {
        "architecture-audit": PipelineDefinition(
            name="architecture-audit",
            stages=["analyzer", "architect"],
            parse_input=_parse_audit_input,
            build_agents=_build_audit_agents,
            adapt_hooks=_ArchitectureAuditHooksAdapter,
            create_pipeline=_create_audit_pipeline,
            run_pipeline=_run_audit_graph,
        ),
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


class ArchitectureAuditService:
    """Typed facade over the generic path; behavior unchanged.

    `tracing_backend` and `callbacks_factory` are injectable ports (Phase 1):
    production uses the LangSmith backend and the HTTP backend sink; tests
    inject recorders or no-ops. Defaults preserve the previous behaviour.
    """

    def __init__(
        self,
        execution_service: AgentExecutionService | None = None,
        callbacks_factory: Callable[[], CallbackSink | None] | None = None,
        tracing_backend: TracingBackend | None = None,
    ) -> None:
        self._exec = execution_service or AgentExecutionService()
        self._callbacks_factory = callbacks_factory or _default_callbacks
        self._tracing = tracing_backend or LangSmithTracingBackend()
        self._generic = GenericPipelineService(
            execution_service=self._exec,
            callbacks_factory=self._callbacks_factory,
            tracing_backend=self._tracing,
        )

    async def run(
        self,
        input_data: PipelineInput,
        config: ExecutionConfig,
        execution_ids: PipelineExecutionIds | None,
        timeout_seconds: int = DEFAULT_PIPELINE_TIMEOUT_SECONDS,
        stage_configs: PipelineStageConfigs | None = None,
    ) -> dict:
        """Run the graph and return both agents' outputs as plain dicts."""
        return await self._generic.run(
            "architecture-audit",
            input_data.model_dump(),
            config,
            stage_configs=(
                {"analyzer": stage_configs.analyzer, "architect": stage_configs.architect}
                if stage_configs
                else None
            ),
            execution_ids=(
                {"analyzer": execution_ids.analyzer, "architect": execution_ids.architect}
                if execution_ids is not None
                else None
            ),
            timeout_seconds=timeout_seconds,
        )


def _default_callbacks() -> CallbackSink | None:
    return default_callback_sink()


@lru_cache(maxsize=1)
def get_pipeline_service() -> ArchitectureAuditService:
    return ArchitectureAuditService()


@lru_cache(maxsize=1)
def get_generic_pipeline_service() -> GenericPipelineService:
    return GenericPipelineService()
