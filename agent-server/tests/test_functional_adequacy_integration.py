"""Pruebas de integración del agente de Adecuación Funcional."""

import asyncio
from unittest.mock import patch

from server.api.schemas import ExecutionConfig, ModelConfig
from server.app.execution_service import AgentExecutionService


def test_functional_adequacy_runs_through_execution_service():
    service = AgentExecutionService()

    assert "functional_adequacy" in service.list_agents()

    description = service.describe_agent("functional_adequacy")
    assert description["input_schema"]["title"] == "FunctionalAdequacyInput"
    assert description["output_schema"]["title"] == "FunctionalAdequacyOutput"

    config = ExecutionConfig(
        model=ModelConfig(
            provider="gemini",
            name="gemini-3.1-flash-lite",
        ),
        timeout_seconds=60,
    )

    payload = {
        "requirements": [
            {
                "requirement_id": "REQ-001",
                "description": "El sistema debe permitir autenticar usuarios.",
            }
        ],
        "code_fragments": [],
    }

    async def unexpected_generate(*args, **kwargs):
        raise AssertionError("No debe invocarse el LLM sin fragmentos de código")

    with patch(
        "server.agents.functional_adequacy.agent.traced_generate",
        new=unexpected_generate,
    ):
        result = asyncio.run(
            service.run(
                agent_type="functional_adequacy",
                config=config,
                payload=payload,
            )
        )

    assert result.evaluated_attribute == "functional_adequacy"
    assert result.total_requirements == 1
    assert result.fulfilled_requirements == 0
    assert result.results[0].status == "evidencia_insuficiente"
    assert result.score == 0.0
