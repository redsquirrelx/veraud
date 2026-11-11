
"""Prepara evidencias de repositorios para Adecuación Funcional."""

from pathlib import Path

from ...config.logs import get_logger
from ...services.repository_analysis import RepositoryAnalysisService
from .exploratory import (
    extract_document_references,
    extract_repository_capabilities,
)
from .schemas import (
    CodeFragment,
    FunctionalAdequacyInput,
    FunctionalRequirement,
    RepositoryContext,
)

logger = get_logger("functional-adequacy-repository-adapter")

SUPPORTED_LANGUAGES = frozenset({"python", "javascript", "typescript"})
MAX_FRAGMENT_LINES = 80
MAX_FRAGMENTS = 500


def build_code_fragments(snapshot) -> list[CodeFragment]:
    """Convierte archivos procesados en fragmentos rastreables."""
    fragments = []

    for source_file in getattr(snapshot, "files", ()):
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


def _analysis_limitations(snapshot) -> list[str]:
    coverage = getattr(snapshot, "coverage", None)
    if coverage is None:
        return []

    limitations = list(getattr(coverage, "limitations", ()))
    unsupported = getattr(coverage, "unsupported_source_languages", ())
    if unsupported:
        limitations.append(
            "Lenguajes de código fuente no soportados: "
            + ", ".join(sorted(unsupported))
            + "."
        )
    return limitations


def _analysis_issues(snapshot) -> list[str]:
    coverage = getattr(snapshot, "coverage", None)
    if coverage is None:
        return []

    return [
        f"{issue.path}: {issue.message}"
        for issue in getattr(coverage, "issues", ())
    ]


def _repository_context(snapshot, fragments: list[CodeFragment]):
    repository = getattr(snapshot, "repository", None)
    return RepositoryContext(
        repository_name=(
            getattr(repository, "name", None)
            if repository is not None
            else None
        ),
        capabilities=extract_repository_capabilities(snapshot, fragments),
        document_references=extract_document_references(snapshot),
        analysis_limitations=_analysis_limitations(snapshot),
        analysis_issues=_analysis_issues(snapshot),
    )


def prepare_snapshot_input(snapshot, requirements: list[FunctionalRequirement]) -> FunctionalAdequacyInput:
    """Reuse the audit's retained snapshot, without reading a second revision."""
    fragments = build_code_fragments(snapshot)
    return FunctionalAdequacyInput(
        requirements=requirements,
        code_fragments=fragments,
        repository_context=_repository_context(snapshot, fragments),
    )


async def prepare_repository_input(
    repository_path: str | Path,
    requirements: list[FunctionalRequirement],
) -> FunctionalAdequacyInput:
    """Prepara la entrada del agente usando el analizador compartido."""
    try:
        snapshot = await RepositoryAnalysisService().analyze(
            str(repository_path)
        )
    except Exception as error:  # noqa: BLE001 - el fallo se informa en el resultado.
        logger.warning(
            "Repository analysis failed for %s: %s",
            repository_path,
            error,
        )
        return FunctionalAdequacyInput(
            requirements=requirements,
            code_fragments=[],
            repository_context=RepositoryContext(
                repository_name=Path(repository_path).name,
                analysis_issues=[
                    (
                        "El análisis del repositorio falló: "
                        f"{type(error).__name__}: {error}"
                    )
                ],
            ),
        )

    return prepare_snapshot_input(snapshot, requirements)
