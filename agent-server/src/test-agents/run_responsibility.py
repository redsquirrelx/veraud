r"""Ejecutar desde agent-server (PowerShell):

    uv run python src/test-agents/run_responsibility.py C:\repos\proyecto

Lee proveedor/modelo de config/dev-agents.yaml (agents.dummy por defecto) y
LLM_API_KEY del .env de la raíz. Otra entrada: --agent-config NOMBRE.
Opcionales: --request solicitud.json --config limites.json --max-files 2000.
Tracing: LANGSMITH_API_KEY y LANGSMITH_PROJECT en .env. Para ocultar código:
LANGSMITH_HIDE_INPUTS=true y LANGSMITH_HIDE_OUTPUTS=true.
Realiza llamadas reales con posible coste; no modifica el repositorio auditado.
Pruebas offline: uv run pytest src/test-agents/test_responsibility.py -q
"""

import argparse
import asyncio
from pathlib import Path
from types import SimpleNamespace

from run_architecture_boundary import load_test_model, run_audit

from server.agents.maintainability.modularity.responsibility import (
    ResponsibilityAgent,
    ResponsibilityConfig,
    ResponsibilityRequest,
)
from server.runtimes.repository.model_runtime import close_model_clients


async def run(args):
    root = Path(args.repository).resolve()
    request = ResponsibilityRequest.model_validate_json(
        Path(args.request).read_text(encoding="utf-8"),
    ) if args.request else ResponsibilityRequest()
    config = ResponsibilityConfig.model_validate_json(
        Path(args.config).read_text(encoding="utf-8"),
    ) if args.config else ResponsibilityConfig()
    model, settings = load_test_model(args.agent_config)
    try:
        await run_audit(args, root, request, config, model, settings, agent_class=ResponsibilityAgent)
    finally:
        await close_model_clients(SimpleNamespace(llm=model))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("repository")
    parser.add_argument("--agent-config", default="dummy", help="Entry in config/dev-agents.yaml")
    parser.add_argument("--request", help="JSON ResponsibilityRequest with context/criteria")
    parser.add_argument("--config", help="JSON ResponsibilityConfig with limits/prompt overrides")
    parser.add_argument("--max-files", type=int, default=2000)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
