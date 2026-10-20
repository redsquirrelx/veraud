
import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from server.agents.functional_adequacy.repository_adapter import (
    MAX_FRAGMENTS,
    build_code_fragments,
    prepare_repository_input,
)
from server.agents.functional_adequacy.schemas import FunctionalRequirement


def make_source(
    file_id="file:001",
    path="src/example.py",
    language="python",
    status="processed",
    content="def example():\n    return True",
):
    return SimpleNamespace(
        id=file_id,
        path=path,
        language=language,
        status=status,
        content=content,
    )


def test_builds_traceable_fragments():
    snapshot = SimpleNamespace(
        files=[make_source(content="first\nsecond\nthird")]
    )

    fragments = build_code_fragments(snapshot)

    assert len(fragments) == 1
    assert fragments[0].fragment_id == "file:001:1-3"
    assert fragments[0].file_path == "src/example.py:1-3"
    assert fragments[0].code == "first\nsecond\nthird"


def test_excludes_unsupported_and_unprocessed_files():
    snapshot = SimpleNamespace(
        files=[
            make_source(file_id="1", status="skipped"),
            make_source(file_id="2", language="markdown"),
            make_source(file_id="3", content=""),
            make_source(file_id="4", path="src/valid.py"),
        ]
    )

    fragments = build_code_fragments(snapshot)

    assert len(fragments) == 1
    assert fragments[0].file_path == "src/valid.py:1-2"


def test_splits_fragments_into_line_ranges():
    snapshot = SimpleNamespace(
        files=[make_source(content="\n".join(["line"] * 81))]
    )

    fragments = build_code_fragments(snapshot)

    assert len(fragments) == 2
    assert fragments[0].file_path == "src/example.py:1-80"
    assert fragments[1].file_path == "src/example.py:81-81"


def test_respects_fragment_limit():
    snapshot = SimpleNamespace(
        files=[make_source(content="\n".join(["line"] * (80 * (MAX_FRAGMENTS + 1))))]
    )

    fragments = build_code_fragments(snapshot)

    assert len(fragments) == MAX_FRAGMENTS


def test_prepare_repository_input_preserves_requirements():
    requirement = FunctionalRequirement(
        requirement_id="REQ-001",
        description="El sistema debe permitir iniciar sesión.",
    )
    snapshot = SimpleNamespace(
        files=[make_source()]
    )

    async def fake_analyze(self, repository_path):
        assert repository_path == "/tmp/example-repository"
        return snapshot

    with patch(
        "server.agents.functional_adequacy.repository_adapter."
        "RepositoryAnalysisService.analyze",
        new=fake_analyze,
    ):
        result = asyncio.run(
            prepare_repository_input(
                "/tmp/example-repository",
                [requirement],
            )
        )

    assert result.requirements == [requirement]
    assert len(result.code_fragments) == 1
    assert result.code_fragments[0].file_path == "src/example.py:1-2"