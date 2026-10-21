r"""Ejecutar desde agent-server (PowerShell):

    uv run python src/test-agents/run_dependency_impact.py C:\repos\proyecto

Proveedor/modelo: config/dev-agents.yaml, agents.dummy por defecto.
Credenciales: LLM_API_KEY en el .env de la raíz. Otra entrada: --agent-config NOMBRE.
Opcionales: --request solicitud.json --config limites.json --max-files 2000.
Tracing: LANGSMITH_API_KEY y LANGSMITH_PROJECT en .env; para ocultar código/prompts:
LANGSMITH_HIDE_INPUTS=true y LANGSMITH_HIDE_OUTPUTS=true.
Realiza llamadas reales con posible coste; no modifica el repositorio auditado.
Pruebas offline: uv run pytest src/test-agents/test_dependency_impact.py -q
"""

import argparse
import asyncio
from pathlib import Path
from types import SimpleNamespace

from run_architecture_boundary import load_test_model, run_audit

from server.agents.maintainability.modularity.dependency_impact import (
    DependencyImpactAgent,
    DependencyImpactConfig,
    DependencyImpactRequest,
)
from server.config.runner import load_runner_config
from server.runtimes.repository.model_runtime import close_model_clients


async def run(args):
    root = Path(args.repository).resolve()
    request = DependencyImpactRequest.model_validate_json(
        Path(args.request).read_text(encoding="utf-8"),
    ) if args.request else DependencyImpactRequest()
    config, token_policy = load_runner_config(DependencyImpactConfig, args.config)
    model, settings = load_test_model(args.agent_config)
    try:
        await run_audit(args, root, request, config, model, settings, agent_class=DependencyImpactAgent, token_policy=token_policy)
    finally:
        await close_model_clients(SimpleNamespace(llm=model))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("repository")
    parser.add_argument("--agent-config", default="dummy", help="Entry in config/dev-agents.yaml")
    parser.add_argument("--request", help="JSON DependencyImpactRequest with context/criteria")
    parser.add_argument("--config", help="JSON DependencyImpactConfig with limits/prompts/depth")
    parser.add_argument("--max-files", type=int, default=2000)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
