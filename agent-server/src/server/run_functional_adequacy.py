
"""CLI para ejecutar el pipeline de Adecuación Funcional."""

import argparse
import asyncio
import json
import os
from pathlib import Path

from .agents.functional_adequacy.repository_adapter import (
    prepare_repository_input,
)
from .agents.functional_adequacy.schemas import FunctionalRequirement
from .api.schemas import ExecutionConfig, ModelConfig
from .app.pipeline_service import GenericPipelineService


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Ejecutar una auditoría de Adecuación Funcional."
    )
    parser.add_argument(
        "input",
        type=Path,
        help="JSON con requisitos y, opcionalmente, fragmentos de código.",
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

    async def execute():
        payload = json.loads(args.input.read_text(encoding="utf-8"))

        if args.repository is not None:
            requirements = [
                FunctionalRequirement.model_validate(item)
                for item in payload["requirements"]
            ]
            prepared = await prepare_repository_input(
                args.repository,
                requirements,
            )
            payload = prepared.model_dump()

            print(
                "Preparación automática completada: "
                f"{len(prepared.requirements)} requisitos, "
                f"{len(prepared.code_fragments)} fragmentos."
            )

        config = ExecutionConfig(
            model=ModelConfig(provider=args.provider, name=args.model),
            api_key=os.environ["LLM_API_KEY"],
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