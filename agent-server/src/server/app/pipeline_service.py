"""One HTTP call for the whole describe-then-frame flow.

The backend creates two `agent_execution` rows (analyzer + architect) and hands
their ids over. This service drives the `ArchitectureAuditPipeline` LangGraph
with reporting hooks, so each stage closes its own row. The graph owns the
analyze -> describe order; this service owns nothing about it. Agents never
create rows; they only ever close the ones they were given.

Without `execution_ids` nothing is reported, exactly like a dev runner: the
pipeline still runs and returns both outputs.
"""

import asyncio
from collections.abc import Callable
from functools import lru_cache

from pydantic import BaseModel, Field

from ..agents.analyzer.schemas import ProjectDescription
from ..agents.architect.schemas import ArchitectureDescription
from ..api.schemas import ExecutionConfig
from ..config.logs import get_logger
from ..infrastructure.callback.schemas import ExecutionOutcome
from ..pipelines.architecture_audit import ArchitectureAuditPipeline
from .callback_port import CallbackSink, default_callback_sink
from .execution_service import AgentExecutionService
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


class _ReportingHooks:
    """AuditHooks that close one backend row per stage.

    Tracks which rows were marked Running but never closed, so a failure can
    fail them instead of leaving the Dock hanging on Waiting forever. Also
    remembers whether the analysis landed, so a failure closes the right rows:
    analyzer Failed plus architect Skipped when the analyzer went down, versus
    architect Failed alone when only the second stage did.
    """

    def __init__(
        self,
        callbacks: CallbackSink | None,
        execution_ids: PipelineExecutionIds,
    ) -> None:
        self._callbacks = callbacks
        self._ids = execution_ids
        self.open_rows: set[int] = set()
        self.analysis_done = False

    async def on_analyzer_start(self) -> None:
        await self._mark_running(self._ids.analyzer)

    async def on_analysis(self, analysis: ProjectDescription) -> None:
        await self._report(self._ids.analyzer, analysis)
        self.analysis_done = True

    async def on_architect_start(self) -> None:
        await self._mark_running(self._ids.architect)

    async def on_description(self, description: ArchitectureDescription) -> None:
        await self._report(self._ids.architect, description)

    async def close_failed(self, error: str) -> None:
        """Close whatever the failure left open."""
        if not self.analysis_done:
            # The architect never ran, so its row must not stay Waiting: it is
            # closed as skipped, and the analyzer carries the real failure.
            await self._report_failure(self._ids.analyzer, error)
            await self._report_failure(
                self._ids.architect, f"Skipped: the analyzer failed ({error})"
            )
        else:
            # The analyzer already closed as Completed: its result stands.
            await self._report_failure(self._ids.architect, error)

    async def fail_open(self, error: str) -> None:
        for execution_id in (self._ids.analyzer, self._ids.architect):
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


class ArchitectureAuditService:
    """Drives the audit graph, reporting each stage to its own row.

    `tracing` and `callbacks_factory` are injectable ports (Phase 1): production
    uses the LangSmith backend and the HTTP backend sink; tests inject
    recorders or no-ops. Defaults preserve the previous behaviour.
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

    async def run(
        self,
        input_data: PipelineInput,
        config: ExecutionConfig,
        execution_ids: PipelineExecutionIds | None,
        timeout_seconds: int = DEFAULT_PIPELINE_TIMEOUT_SECONDS,
        stage_configs: PipelineStageConfigs | None = None,
    ) -> dict:
        """Run the graph and return both agents' outputs as plain dicts."""
        analyzer, _ = self._exec.build_agent(
            "analyzer", stage_configs.analyzer if stage_configs else config
        )
        architect, _ = self._exec.build_agent(
            "architect", stage_configs.architect if stage_configs else config
        )
        callbacks = self._callbacks_factory() if execution_ids is not None else None

        if execution_ids is not None and callbacks is None:
            logger.warning(
                "execution_ids given but no backend url is configured, "
                "so progress cannot be reported"
            )

        hooks = (
            _ReportingHooks(callbacks, execution_ids)
            if execution_ids is not None
            else None
        )
        pipeline = ArchitectureAuditPipeline(analyzer, architect, hooks=hooks)

        try:
            return await self._tracing.wrap_pipeline(
                asyncio.wait_for(
                    pipeline.run(
                        input_data.root_path,
                        max_files=input_data.max_files,
                        max_depth=input_data.max_depth,
                        max_read_rounds=input_data.max_read_rounds,
                        max_files_per_round=input_data.max_files_per_round,
                    ),
                    timeout_seconds,
                ),
                name="architecture-audit",
                timeout_seconds=timeout_seconds,
            )
        except TimeoutError:
            logger.error("Pipeline timed out after %ss", timeout_seconds)
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
def get_pipeline_service() -> ArchitectureAuditService:
    return ArchitectureAuditService()
