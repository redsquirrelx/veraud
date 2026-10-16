r"""Ejecutar desde agent-server:

    uv run python src/test-agents/run_modularity.py C:\repos\proyecto

Usa config/dev-agents.yaml (--agent-config dummy), LLM_API_KEY del .env y
LangSmithTracingBackend opcional con LANGSMITH_API_KEY. Hace llamadas reales
con coste; no escribe en el repositorio auditado. --request y --config aceptan JSON.
"""

import argparse
import asyncio
from pathlib import Path
from types import SimpleNamespace

from run_architecture_boundary import load_test_model, run_audit

from server.agents.maintainability.modularity.coordinator import (
    ModularityAgent,
    ModularityConfig,
    ModularityRequest,
)
from server.runtimes.repository.model_runtime import close_model_clients


async def run(args):
    request = ModularityRequest.model_validate_json(Path(args.request).read_text(encoding="utf-8")) if args.request else ModularityRequest()
    config = ModularityConfig.model_validate_json(Path(args.config).read_text(encoding="utf-8")) if args.config else ModularityConfig()
    model, settings = load_test_model(args.agent_config)
    try:
        await run_audit(args, Path(args.repository).resolve(), request, config, model, settings, agent_class=ModularityAgent)
    finally:
        await close_model_clients(SimpleNamespace(llm=model))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository")
    parser.add_argument("--agent-config", default="dummy")
    parser.add_argument("--request")
    parser.add_argument("--config")
    parser.add_argument("--max-files", type=int, default=2000)
    asyncio.run(run(parser.parse_args()))
