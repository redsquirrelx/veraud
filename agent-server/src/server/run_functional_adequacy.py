
"""CLI para ejecutar el pipeline de Adecuación Funcional."""

import argparse
import asyncio
import json
import os
from pathlib import Path

from server.app.execution_config import ExecutionConfig, ModelConfig

from .agents.functional_adequacy.repository_adapter import (
    prepare_repository_input,
)
from .agents.functional_adequacy.schemas import FunctionalRequirement
from .app.pipeline_service import GenericPipelineService


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Ejecutar una auditoría de Adecuación Funcional."
    )
    parser.add_argument(
        "input",
        type=Path,
        nargs="?",
        help=(
            "JSON opcional con requisitos y, opcionalmente, fragmentos de "
            "código. Si se omite junto con --repository, la auditoría es "
            "exploratoria."
        ),
    )
    parser.add_argument(
        "--repository",
        type=Path,
        help="Ruta del repositorio que se analizará automáticamente.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Archivo JSON donde se guardará el resultado.",
    )
    parser.add_argument("--provider", default="gemini")
    parser.add_argument("--model", default="gemini-3.8-flash")
    parser.add_argument("--timeout", type=int, default=120)

    args = parser.parse_args(argv)

    if args.input is None and args.repository is None:
        parser.error(
            "Debe proporcionar un repositorio (--repository) o un archivo "
            "JSON de entrada."
        )

    async def execute():
        payload = (
            json.loads(args.input.read_text(encoding="utf-8"))
            if args.input is not None
            else {}
        )

        if args.repository is not None:
            requirements = [
                FunctionalRequirement.model_validate(item)
                for item in payload.get("requirements", [])
            ]
            prepared = await prepare_repository_input(
                args.repository,
                requirements,
            )
            payload = prepared.model_dump()

            mode = (
                "basado en requisitos"
                if prepared.requirements
                else "exploratorio"
            )
            print(
                "Preparación automática completada: "
                f"modo {mode}, "
                f"{len(prepared.requirements)} requisitos, "
                f"{len(prepared.code_fragments)} fragmentos, "
                f"{len(prepared.repository_context.capabilities) if prepared.repository_context else 0} "
                "capacidades."
            )

        config = ExecutionConfig(
            model=ModelConfig(provider=args.provider, name=args.model),
            api_key=os.environ.get("LLM_API_KEY"),
            timeout_seconds=args.timeout,
        )

        return await GenericPipelineService().run(
            pipeline_name="functional-adequacy",
            input_data=payload,
            config=config,
            timeout_seconds=args.timeout,
        )

    result = asyncio.run(execute())

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print("Auditoría de Adecuación Funcional finalizada.")

    if result.get("audit_mode") == "exploratory":
        print(
            "Modo exploratorio: "
            f"{len(result.get('capabilities', []))} capacidades, "
            f"{len(result.get('findings', []))} hallazgos."
        )
        for summary in result.get("subattributes", []):
            print(
                f"{summary['attribute']}: "
                f"{summary['confirmed']} confirmados, "
                f"{summary['probable']} probables, "
                f"{summary['unverified']} no verificados."
            )
    else:
        for item in result["results"]:
            print(
                f"Requisito: {item['requirement_id']} | "
                f"Clasificación: {item['status']} | "
                f"Evidencias: {len(item['evidence'])}"
            )

    print(f"Resultado guardado: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
