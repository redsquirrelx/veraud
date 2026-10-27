"""Definición del pipeline de Adecuación Funcional."""

from __future__ import annotations

from typing import Any

from server.app.pipeline_contracts import PipelineDefinition, bind_no_context

STAGE = "functional_adequacy"


def parse_functional_input(raw: dict) -> dict:
    # El esquema del agente valida los requisitos y fragmentos al ejecutarse.
    return raw


async def build_functional_agents(
    exec_service: Any,
    config: Any,
    stage_configs: dict | None,
    parsed: dict,
    timeout_seconds: int,
) -> tuple[dict, dict]:
    # Reutilizar el servicio compartido sin instanciar otro agente.
    selected_config = (stage_configs or {}).get(STAGE) or config
    return {STAGE: exec_service}, {"config": selected_config}


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
    parsed: dict,
    ctx: dict,
) -> dict:
    hooks = pipeline["hooks"]

    if hooks is not None:
        await hooks.on_stage_start(STAGE)

    result = await pipeline["service"].run(
        agent_type=STAGE,
        config=ctx["config"],
        payload=parsed,
        blackboard=ctx.get("blackboard"),
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
        bind_context=bind_no_context,
        requires_agent_execution_service=True,
    )
