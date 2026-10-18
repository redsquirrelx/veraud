
"""Prepara evidencias de repositorios para Adecuación Funcional."""

from pathlib import Path

from ...services.repository_analysis import RepositoryAnalysisService
from .schemas import CodeFragment, FunctionalAdequacyInput, FunctionalRequirement

SUPPORTED_LANGUAGES = frozenset({"python", "javascript", "typescript"})
MAX_FRAGMENT_LINES = 80
MAX_FRAGMENTS = 500


def build_code_fragments(snapshot) -> list[CodeFragment]:
    """Convierte archivos procesados en fragmentos rastreables."""
    fragments = []

    for source_file in snapshot.files:
        if (
            source_file.status != "processed"
            or source_file.language not in SUPPORTED_LANGUAGES
            or not source_file.content
        ):
            continue

        lines = source_file.content.splitlines()

        for start in range(0, len(lines), MAX_FRAGMENT_LINES):
            if len(fragments) >= MAX_FRAGMENTS:
                return fragments

            chunk = lines[start : start + MAX_FRAGMENT_LINES]
            if not any(line.strip() for line in chunk):
                continue

            start_line = start + 1
            end_line = start + len(chunk)

            fragments.append(
                CodeFragment(
                    fragment_id=f"{source_file.id}:{start_line}-{end_line}",
                    file_path=(
                        f"{source_file.path}:{start_line}-{end_line}"
                    ),
                    code="\n".join(chunk),
                )
            )

    return fragments


async def prepare_repository_input(
    repository_path: str | Path,
    requirements: list[FunctionalRequirement],
) -> FunctionalAdequacyInput:
    """Prepara la entrada del agente usando el analizador compartido."""
    snapshot = await RepositoryAnalysisService().analyze(
        str(repository_path)
    )

    return FunctionalAdequacyInput(
        requirements=requirements,
        code_fragments=build_code_fragments(snapshot),
    )