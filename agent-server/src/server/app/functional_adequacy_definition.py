"""Definición del pipeline de Adecuación Funcional."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from ..agents.functional_adequacy.repository_adapter import (
    prepare_repository_input,
)
from ..agents.functional_adequacy.schemas import (
    CodeFragment,
    FunctionalAdequacyInput,
    FunctionalRequirement,
    RepositoryContext,
)
from ..config.settings import resolve_workspace_root
from .execution_service import InvalidConfigError
from .pipeline_service import PipelineDefinition

STAGE = "functional_adequacy"


class FunctionalAdequacyPipelineInput(BaseModel):
    """Entrada del pipeline: repositorio, requisitos o evidencia ya preparada."""

    root_path: str | None = Field(
        default=None,
        description="Checkout dentro del workspace compartido que se analizará.",
    )
    requirements: list[FunctionalRequirement] = Field(default_factory=list)
    code_fragments: list[CodeFragment] = Field(default_factory=list)
    repository_context: RepositoryContext | None = None


def parse_functional_input(raw: dict) -> FunctionalAdequacyPipelineInput:
    try:
        return FunctionalAdequacyPipelineInput.model_validate(raw)
    except ValidationError as error:
        raise InvalidConfigError(f"Invalid pipeline input: {error}") from None


def _workspace_repository(root_path: str) -> Path:
    root = Path(root_path).expanduser().resolve()
    workspace = resolve_workspace_root()
    if root.parent != workspace:
        raise InvalidConfigError(
            f"root_path must be a checkout directly inside the shared workspace ({workspace})"
        )
    return root


async def build_functional_agents(
    exec_service: Any,
    config: Any,
    stage_configs: dict | None,
    parsed: FunctionalAdequacyPipelineInput,
    timeout_seconds: int,
) -> tuple[dict, dict]:
    if parsed.root_path is not None:
        prepared = await prepare_repository_input(
            _workspace_repository(parsed.root_path),
            parsed.requirements,
        )
    else:
        prepared = FunctionalAdequacyInput(
            requirements=parsed.requirements,
            code_fragments=parsed.code_fragments,
            repository_context=parsed.repository_context,
        )

    selected_config = (stage_configs or {}).get(STAGE) or config
    return {STAGE: exec_service}, {
        "config": selected_config,
        "input": prepared,
        "uses_model": bool(prepared.requirements),
    }


def adapt_functional_hooks(generic: Any) -> Any:
    return generic


def create_functional_pipeline(
    agents: dict,
    graph_hooks: Any,
    ctx: dict,
) -> dict:
    return {"service": agents[STAGE], "hooks": graph_hooks}


async def run_functional_pipeline(
    pipeline: dict,
    parsed: FunctionalAdequacyPipelineInput,
    ctx: dict,
) -> dict:
    hooks = pipeline["hooks"]

    if hooks is not None:
        await hooks.on_stage_start(STAGE)

    result = await pipeline["service"].run(
        agent_type=STAGE,
        config=ctx["config"],
        payload=ctx["input"].model_dump(),
        model_required=ctx["uses_model"],
    )

    if hooks is not None:
        await hooks.on_stage_result(STAGE, result)

    return result.model_dump(mode="json")


def functional_adequacy_definition() -> PipelineDefinition:
    return PipelineDefinition(
        name="functional-adequacy",
        stages=[STAGE],
        parse_input=parse_functional_input,
        build_agents=build_functional_agents,
        adapt_hooks=adapt_functional_hooks,
        create_pipeline=create_functional_pipeline,
        run_pipeline=run_functional_pipeline,
        agent_types={STAGE: STAGE},
    )
