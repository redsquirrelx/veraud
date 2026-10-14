"""project-architecture pipeline definition (Phase 3).

Registers orientation → architecture → semantic_validation as one generic
pipeline. Unlike architecture-audit, these agents are not `BaseAgent`s: they
run over a retained repository snapshot with per-stage models behind a
`ModelGateway`, exactly like the `run_project_architecture` CLI runner. This
module reuses that lifecycle (snapshot, budget, gateways, pipeline) so the CLI
and the HTTP endpoint produce the same `ProjectArchitecturePipelineResult`.

Stage rows: orientation, architecture, semantic_validation. The internal
diagram_composition node has no row; its events are filtered out by the
adapter and its output ships embedded in the architecture result.
"""

from __future__ import annotations

from pathlib import Path
from time import monotonic
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, ValidationError

from ..agents.project_architecture import ProjectArchitectureAgent
from ..agents.project_orientation import ProjectOrientationAgent
from ..agents.project_semantic_validation import ProjectSemanticValidationAgent
from ..agents.project_semantic_validation.schemas import ValidationLimits
from ..agents.repository_runtime.model_runtime import (
    ModelGateway,
    close_model_clients,
    create_project_model,
)
from ..agents.repository_runtime.schemas import ExecutionBudget
from ..config.logs import get_logger
from ..config.settings import resolve_workspace_root
from ..pipelines.project_architecture import ProjectArchitecturePipeline
from ..services.repository_analysis import (
    RepositoryAnalysisInput,
    RepositoryAnalysisService,
)
from .execution_service import InvalidConfigError
from .usage_reporting import gateway_progress

if TYPE_CHECKING:
    from ..api.schemas import ExecutionConfig
    from .pipeline_service import GenericReportingHooks, PipelineDefinition

logger = get_logger("pipeline.project-architecture")

STAGES = ["orientation", "architecture", "semantic_validation"]

# Same pacing as the CLI runner (repository_runner.build_parser defaults).
_GATEWAY_INTERVAL = 0
_GATEWAY_MAX_RETRIES = 2
_GATEWAY_BACKOFF = 2


class ProjectArchitectureInput(BaseModel):
    """Where to look, with budgets and stage flags. Mirrors the CLI defaults
    for investigation runs; the shared request deadline doubles as the
    elapsed-time budget."""

    root_path: str = Field(description="Repository checkout to audit")
    max_files: int = Field(default=5000, ge=1)
    max_depth: int = Field(default=30, ge=0)
    max_model_calls: int = Field(default=24, ge=1)
    max_tool_calls: int = Field(default=32, ge=1)
    max_total_tokens: int = Field(default=160000, ge=1000)
    max_input_tokens_per_call: int = Field(default=10000, ge=500)
    max_objective_tokens: int = Field(default=80000, ge=1000)
    max_output_tokens_per_call: int = Field(default=40000, ge=256)
    max_retrieved_characters: int = Field(default=150000, ge=1)
    max_review_claims: int = Field(default=64, ge=1, le=64)
    include_orientation: bool = True
    validate_semantics: bool = True
    allow_return: bool = True
    include_diagram: bool = True


def parse_project_architecture_input(raw: dict) -> ProjectArchitectureInput:
    try:
        return ProjectArchitectureInput.model_validate(raw)
    except ValidationError as error:
        raise InvalidConfigError(f"Invalid pipeline input: {error}") from None


async def build_project_agents(
    exec_service: Any,
    config: ExecutionConfig,
    stage_configs: dict[str, ExecutionConfig] | None,
    parsed: ProjectArchitectureInput,
    timeout_seconds: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Snapshot the repo, then build one model+gateway+agent per stage."""
    import os

    root = Path(parsed.root_path).expanduser().resolve()
    workspace = resolve_workspace_root()
    if root.parent != workspace:
        raise InvalidConfigError(
            f"root_path must be a checkout directly inside the shared workspace ({workspace})"
        )

    snapshot = await RepositoryAnalysisService().analyze(
        RepositoryAnalysisInput(
            root_path=str(root),
            max_files=parsed.max_files,
            max_depth=parsed.max_depth,
        )
    )
    budget = ExecutionBudget(
        max_model_calls=parsed.max_model_calls,
        max_total_tokens=parsed.max_total_tokens,
        max_input_tokens_per_call=parsed.max_input_tokens_per_call,
        max_tokens_per_objective=parsed.max_objective_tokens,
        max_output_tokens_per_call=parsed.max_output_tokens_per_call,
        max_tool_calls=parsed.max_tool_calls,
        max_retrieved_characters=parsed.max_retrieved_characters,
        max_elapsed_seconds=timeout_seconds,
    )
    deadline = monotonic() + timeout_seconds

    if os.environ.get("AGENT_SERVER_SMOKE_MODELS") == "1":
        # Test-only offline protocol check (mirrors the CLI --smoke models):
        # no provider credentials or network, same graphs and snapshots.
        from ..agents.project_architecture.smoke import ArchitectureSmokeModel
        from ..agents.project_semantic_validation.smoke import (
            SemanticValidationSmokeModel,
        )

        shared: dict[str, Any] = {}

        class PipelineSmokeModel(ArchitectureSmokeModel):
            async def generate(self, prompt):
                if "\nVALIDATION_DATA\n" in prompt:
                    return await SemanticValidationSmokeModel().generate(prompt)
                return await super().generate(prompt)

        smoke_model = PipelineSmokeModel() if parsed.validate_semantics else ArchitectureSmokeModel()
        def smoke_gateway():
            return ModelGateway(
                smoke_model, interval=_GATEWAY_INTERVAL,
                max_retries=_GATEWAY_MAX_RETRIES, backoff=_GATEWAY_BACKOFF,
                trace=True,
                remaining_seconds=lambda _deadline=deadline: max(0.0, _deadline - monotonic()),
            )
        agents = {
            "orientation": ProjectOrientationAgent(
                smoke_model, generate=smoke_gateway()
            ),
            "architecture": ProjectArchitectureAgent(
                smoke_model, generate=smoke_gateway()
            ),
            "semantic_validation": ProjectSemanticValidationAgent(
                smoke_model,
                generate=smoke_gateway(),
                limits=ValidationLimits(max_claims=parsed.max_review_claims),
            ),
        }
        logger.info(
            "project-architecture prepared snapshot=%s files=%d (smoke models)",
            snapshot.repository.snapshot_hash[:12], len(snapshot.files),
        )
        return agents, {
            "snapshot": snapshot,
            "budget": budget,
            "workspace_root": workspace,
            "deadline": deadline,
            "models": shared,
        }

    models: dict[str, Any] = {}
    agents: dict[str, Any] = {}
    for stage in STAGES:
        stage_config = (stage_configs or {}).get(stage) or config
        settings, credentials, _ = exec_service.resolve_model_settings(stage, stage_config)
        model = create_project_model(settings, credentials)
        gateway = ModelGateway(
            model,
            interval=_GATEWAY_INTERVAL,
            max_retries=_GATEWAY_MAX_RETRIES,
            backoff=_GATEWAY_BACKOFF,
            trace=True,
            remaining_seconds=lambda _deadline=deadline: max(0.0, _deadline - monotonic()),
        )
        models[stage] = model
        if stage == "orientation":
            agents[stage] = ProjectOrientationAgent(model, generate=gateway)
        elif stage == "architecture":
            agents[stage] = ProjectArchitectureAgent(model, generate=gateway)
        else:
            agents[stage] = ProjectSemanticValidationAgent(
                model,
                generate=gateway,
                limits=ValidationLimits(max_claims=parsed.max_review_claims),
            )

    logger.info(
        "project-architecture prepared snapshot=%s files=%d",
        snapshot.repository.snapshot_hash[:12], len(snapshot.files),
    )
    ctx = {
        "snapshot": snapshot,
        "budget": budget,
        "workspace_root": workspace,
        "deadline": deadline,
        "models": models,
    }
    return agents, ctx


class ProjectArchitectureHooksAdapter:
    """Forward only row-backed stages; the internal diagram_composition node,
    stage skips and architecture revisions have no backend row and are
    ignored for reporting (their outputs stay embedded in the results)."""

    _TRACKED = frozenset(STAGES)

    def __init__(self, generic: GenericReportingHooks) -> None:
        self._generic = generic
        self._architecture_result: BaseModel | None = None
        self._semantic_result: BaseModel | None = None

    def bind_usage(self, agents, budget):
        for stage in STAGES:
            gateway = agents[stage].generate
            self._generic.register_usage(stage, lambda gateway=gateway: gateway_progress(gateway, budget))

            async def on_usage(source, stage=stage):
                await self._generic.on_stage_progress(stage, gateway_progress(source, budget))

            gateway.on_usage = on_usage

    async def on_stage_start(self, stage: str) -> None:
        if stage in self._TRACKED:
            await self._generic.on_stage_start(stage)

    async def on_stage_result(self, stage: str, result: BaseModel) -> None:
        if stage == "architecture":
            # The same agent may still compose diagrams and revise its report.
            if self._architecture_result is None:
                self._architecture_result = result
            self._generic.retain_partial(stage, result)
            return
        if stage == "semantic_validation" and self._architecture_result is not None:
            self._semantic_result = result
            self._generic.retain_partial(stage, result)
            return
        if stage in self._TRACKED:
            await self._generic.on_stage_result(stage, result)

    async def finish(self, result):
        if self._architecture_result is not None:
            await self._generic.on_stage_result("architecture", result.architecture)
        if self._semantic_result is not None:
            await self._generic.on_stage_result("semantic_validation", self._semantic_result)

    async def on_stage_skip(self, stage: str, reason: str) -> None:
        if stage in self._TRACKED:
            await self._generic.on_stage_skip(stage, reason)


def create_project_pipeline(
    agents: dict[str, Any], graph_hooks: Any, ctx: dict[str, Any]
) -> ProjectArchitecturePipeline:
    if graph_hooks is not None:
        graph_hooks.bind_usage(agents, ctx["budget"])
    return ProjectArchitecturePipeline(
        agents["architecture"],
        orientation=agents["orientation"],
        validator=agents["semantic_validation"],
        hooks=graph_hooks,
        on_event=None,
    )


async def run_project_pipeline(
    pipeline: ProjectArchitecturePipeline,
    parsed: ProjectArchitectureInput,
    ctx: dict[str, Any],
) -> dict:
    """Run the graph and return its result as plain dicts. Model clients are
    always released, mirroring the CLI runner's cleanup."""
    try:
        result = await pipeline.run(
            ctx["snapshot"],
            budget=ctx["budget"],
            workspace_root=ctx["workspace_root"],
            include_orientation=parsed.include_orientation,
            validate_semantics=parsed.validate_semantics,
            allow_return=parsed.allow_return,
            include_diagram=parsed.include_diagram,
            deadline=ctx["deadline"],
        )
        if pipeline.hooks is not None:
            await pipeline.hooks.finish(result)
        return result.model_dump(mode="json")
    finally:
        for model in ctx["models"].values():
            await close_model_clients(model)


def project_architecture_definition() -> PipelineDefinition:
    from .pipeline_service import PipelineDefinition

    return PipelineDefinition(
        name="project-architecture",
        stages=list(STAGES),
        parse_input=parse_project_architecture_input,
        build_agents=build_project_agents,
        adapt_hooks=ProjectArchitectureHooksAdapter,
        create_pipeline=create_project_pipeline,
        run_pipeline=run_project_pipeline,
    )
