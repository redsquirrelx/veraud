"""Pruebas del modo exploratorio de Adecuación Funcional."""

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from server.agents.functional_adequacy.agent import FunctionalAdequacyAgent
from server.agents.functional_adequacy.config import FunctionalAdequacyConfig
from server.agents.functional_adequacy.exploratory import (
    _looks_like_stub,
    evaluate_capabilities,
    is_stub_capability,
)
from server.agents.functional_adequacy.repository_adapter import (
    prepare_repository_input,
)
from server.agents.functional_adequacy.schemas import (
    EvidenceLocation,
    FunctionalCapability,
    FunctionalRequirement,
)
from server.app.pipeline_service import GenericPipelineService
from server.run_functional_adequacy import main


class FakeModel:
    pass


def build_agent():
    agent = FunctionalAdequacyAgent.__new__(FunctionalAdequacyAgent)
    agent.model = FakeModel()
    agent.config = FunctionalAdequacyConfig()
    agent._graph = agent._build_graph()
    return agent


def write_repository(root: Path, files: dict[str, str]) -> Path:
    for relative_path, content in files.items():
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


def make_api_repository(root: Path) -> Path:
    return write_repository(
        root,
        {
            "pyproject.toml": (
                '[project]\nname = "demo"\nrequires-python = ">=3.11"\n'
                'dependencies = ["fastapi>=0.100"]\n'
            ),
            "src/app.py": (
                "from fastapi import FastAPI\n\n"
                "app = FastAPI()\n\n"
                '@app.get("/items")\n'
                "def list_items():\n"
                "    return [{\"id\": 1}]\n\n"
                "def helper(value):\n"
                "    return value + 1\n"
            ),
            "src/service.py": (
                "from .app import helper\n\n"
                "class ItemService:\n"
                "    def create(self, value):\n"
                "        return helper(value)\n"
            ),
        },
    )


def test_repository_without_requirements_runs_exploratory_mode(tmp_path):
    repository = make_api_repository(tmp_path / "demo")
    prepared = asyncio.run(prepare_repository_input(repository, []))

    async def unexpected_generate(*args, **kwargs):
        raise AssertionError(
            "El modo exploratorio no debe invocar el modelo"
        )

    with patch(
        "server.agents.functional_adequacy.agent.traced_generate",
        new=unexpected_generate,
    ):
        output = asyncio.run(build_agent().run(prepared))

    assert output.audit_mode == "exploratory"
    assert output.total_requirements == 0
    assert output.fulfilled_requirements == 0
    assert output.results == []
    assert output.score == 0.0
    assert output.score_applicable is False
    assert "no se calcula un porcentaje" in output.score_meaning
    assert prepared.requirements == []
    assert prepared.code_fragments
    assert output.capabilities
    assert output.findings
    assert {
        summary.attribute for summary in output.subattributes
    } == {"completitud", "correccion", "pertinencia"}
    assert output.classification_criteria
    assert any(
        capability.kind == "http_endpoint"
        for capability in output.capabilities
    )
    assert any(
        "No se proporcionaron requisitos funcionales" in item
        for item in output.limitations
    )
    assert output.recommendations


def test_repository_with_requirements_keeps_requirements_mode(tmp_path):
    pytest.importorskip("sentence_transformers")
    repository = make_api_repository(tmp_path / "demo")
    requirement = FunctionalRequirement(
        requirement_id="REQ-001",
        description="El sistema debe listar los elementos disponibles.",
    )
    prepared = asyncio.run(
        prepare_repository_input(repository, [requirement])
    )

    async def fake_generate(model, prompt):
        return json.dumps(
            {
                "status": "cumple",
                "justification": "El endpoint list_items devuelve elementos.",
            }
        )

    with patch(
        "server.agents.functional_adequacy.agent.traced_generate",
        new=fake_generate,
    ):
        output = asyncio.run(build_agent().run(prepared))

    assert output.audit_mode == "requirements_based"
    assert output.total_requirements == 1
    assert output.fulfilled_requirements == 1
    assert output.results[0].status == "cumple"
    assert output.findings == []
    assert output.capabilities == []
    assert output.limitations


def test_repository_without_compatible_source_produces_structured_result(
    tmp_path,
):
    repository = write_repository(
        tmp_path / "docs-only",
        {
            "README.md": "# Documentación\n",
            "main.go": "package main\n",
        },
    )
    prepared = asyncio.run(prepare_repository_input(repository, []))

    async def unexpected_generate(*args, **kwargs):
        raise AssertionError("El modelo no debe ejecutarse")

    with patch(
        "server.agents.functional_adequacy.agent.traced_generate",
        new=unexpected_generate,
    ):
        output = asyncio.run(build_agent().run(prepared))

    assert prepared.code_fragments == []
    assert output.audit_mode == "exploratory"
    assert output.capabilities == []
    assert output.findings == []
    assert output.results == []
    assert output.score == 0.0
    assert any(
        "No se retuvieron fragmentos" in item
        for item in output.limitations
    )
    assert any(
        "No se detectaron capacidades" in item
        for item in output.limitations
    )


def test_repository_without_detectable_entrypoints_uses_symbols(tmp_path):
    repository = write_repository(
        tmp_path / "library",
        {
            "pyproject.toml": (
                '[project]\nname = "library"\nrequires-python = ">=3.11"\n'
            ),
            "src/library/operations.py": (
                "def add(left, right):\n"
                "    return left + right\n"
            ),
        },
    )
    prepared = asyncio.run(prepare_repository_input(repository, []))

    async def unexpected_generate(*args, **kwargs):
        raise AssertionError("El modelo no debe ejecutarse")

    with patch(
        "server.agents.functional_adequacy.agent.traced_generate",
        new=unexpected_generate,
    ):
        output = asyncio.run(build_agent().run(prepared))

    assert output.audit_mode == "exploratory"
    assert output.capabilities
    assert all(
        capability.kind not in {
            "application",
            "cli",
            "http_endpoint",
            "framework_page",
            "public_api",
            "service",
        }
        for capability in output.capabilities
    )
    assert any(
        "No se detectaron puntos de entrada" in item
        for item in output.limitations
    )
    assert any(
        capability.name == "add"
        for capability in output.capabilities
    )


def test_exploratory_evidence_has_valid_paths_and_lines(tmp_path):
    repository = make_api_repository(tmp_path / "demo")
    prepared = asyncio.run(prepare_repository_input(repository, []))

    assert prepared.repository_context is not None
    capabilities = prepared.repository_context.capabilities
    assert capabilities

    checked = 0
    for capability in capabilities:
        for evidence in capability.evidence:
            file_path = repository / evidence.file_path
            assert file_path.is_file()
            if evidence.start_line is not None:
                line_count = len(
                    file_path.read_text(encoding="utf-8").splitlines()
                )
                assert evidence.start_line >= 1
                assert evidence.end_line is not None
                assert evidence.start_line <= evidence.end_line <= line_count
                checked += 1
            if evidence.fragment_id is not None:
                assert any(
                    fragment.fragment_id == evidence.fragment_id
                    for fragment in prepared.code_fragments
                )

    assert checked > 0
    assert any(
        evidence.symbol
        for capability in capabilities
        for evidence in capability.evidence
    )


def test_repository_analysis_failure_is_reported_in_result(tmp_path):
    repository = tmp_path / "broken"

    async def failing_analyze(self, repository_path):
        raise RuntimeError("análisis no disponible")

    with patch(
        "server.agents.functional_adequacy.repository_adapter."
        "RepositoryAnalysisService.analyze",
        new=failing_analyze,
    ):
        prepared = asyncio.run(prepare_repository_input(repository, []))

    assert prepared.code_fragments == []
    assert prepared.repository_context is not None
    assert prepared.repository_context.analysis_issues

    async def unexpected_generate(*args, **kwargs):
        raise AssertionError("El modelo no debe ejecutarse")

    with patch(
        "server.agents.functional_adequacy.agent.traced_generate",
        new=unexpected_generate,
    ):
        output = asyncio.run(build_agent().run(prepared))

    assert output.audit_mode == "exploratory"
    assert any(
        "Incidente de análisis" in item
        for item in output.limitations
    )
    assert output.results == []
    assert output.score == 0.0


def test_analysis_failure_is_reported_in_requirements_mode(tmp_path):
    repository = tmp_path / "broken"
    requirement = FunctionalRequirement(
        requirement_id="REQ-001",
        description="El sistema debe listar los elementos disponibles.",
    )

    async def failing_analyze(self, repository_path):
        raise RuntimeError("análisis no disponible")

    with patch(
        "server.agents.functional_adequacy.repository_adapter."
        "RepositoryAnalysisService.analyze",
        new=failing_analyze,
    ):
        prepared = asyncio.run(
            prepare_repository_input(repository, [requirement])
        )

    async def fake_generate(model, prompt):
        return json.dumps(
            {
                "status": "evidencia_insuficiente",
                "justification": "No hay fragmentos de código.",
            }
        )

    with patch(
        "server.agents.functional_adequacy.agent.traced_generate",
        new=fake_generate,
    ):
        output = asyncio.run(build_agent().run(prepared))

    assert output.audit_mode == "requirements_based"
    assert any(
        "El análisis del repositorio falló" in item
        for item in output.limitations
    )


def test_model_failure_in_requirements_mode_keeps_structured_result(tmp_path):
    repository = make_api_repository(tmp_path / "demo")
    requirement = FunctionalRequirement(
        requirement_id="REQ-001",
        description="El sistema debe listar los elementos disponibles.",
    )
    prepared = asyncio.run(
        prepare_repository_input(repository, [requirement])
    )

    async def failing_generate(model, prompt):
        raise ConnectionError("proveedor no disponible")

    with patch(
        "server.agents.functional_adequacy.agent.traced_generate",
        new=failing_generate,
    ):
        output = asyncio.run(build_agent().run(prepared))

    assert output.audit_mode == "requirements_based"
    assert output.total_requirements == 1
    assert output.fulfilled_requirements == 0
    assert output.results[0].status == "evidencia_insuficiente"
    assert output.score == 0.0
    assert output.recommendations


def test_exploratory_result_is_reproducible(tmp_path):
    repository = make_api_repository(tmp_path / "demo")

    async def run_once():
        prepared = await prepare_repository_input(repository, [])
        with patch(
            "server.agents.functional_adequacy.agent.traced_generate",
            new=lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("El modelo no debe ejecutarse")
            ),
        ):
            return await build_agent().run(prepared)

    first = asyncio.run(run_once())
    second = asyncio.run(run_once())

    assert first.model_dump() == second.model_dump()


def test_cli_accepts_repository_without_input_json(tmp_path, monkeypatch):
    repository = make_api_repository(tmp_path / "demo")
    output_path = tmp_path / "result.json"
    captured = {}

    async def fake_pipeline_run(self, **kwargs):
        captured.update(kwargs)
        return {
            "audit_mode": "exploratory",
            "results": [],
            "capabilities": [],
            "findings": [],
            "subattributes": [],
        }

    monkeypatch.setattr(GenericPipelineService, "run", fake_pipeline_run)

    exit_code = main(
        [
            "--repository",
            str(repository),
            "--output",
            str(output_path),
            "--provider",
            "gemini",
            "--model",
            "gemini-3.8-flash",
        ]
    )

    assert exit_code == 0
    assert output_path.is_file()
    assert captured["pipeline_name"] == "functional-adequacy"
    assert captured["input_data"]["requirements"] == []
    assert captured["input_data"]["code_fragments"]
    assert (
        captured["input_data"]["repository_context"]["capabilities"]
    )


@pytest.mark.parametrize(
    "snippet",
    [
        "pass",
        "pass  # TODO",
        "...",
        "raise NotImplementedError",
        'raise NotImplementedError("pending")',
        'throw new Error("not implemented")',
        "def pending():\n    pass",
        'def documented():\n    """Pendiente de implementar."""',
        "def commented():\n    # TODO implementar\n    # FIXME pendiente",
    ],
)
def test_looks_like_stub_detects_incomplete_implementations(snippet):
    assert _looks_like_stub(snippet) is True


@pytest.mark.parametrize(
    "snippet",
    [
        "return check_password(username, password)",
        "return bypass_checks(user)",
        "return passphrase",
        "return score >= 60",
        "return compass.bearing()",
        'return "please pass"',
        "return sum(...values)",
        "return a + b  # TODO tune",
        'return data.get("password")',
        "todo_list.append(1)",
        "TODO_LIST = []",
        'throw new Error("Invalid input")',
    ],
)
def test_looks_like_stub_ignores_legitimate_identifiers(snippet):
    assert _looks_like_stub(snippet) is False


@pytest.mark.parametrize(
    "snippet",
    [
        "def calculate(): return 10",
        "async def fetch_data(): return await get_data()",
        "function calculate() { return 10; }",
        "async function fetch_data() { return await getData(); }",
        "export function calculate() { return 10; }",
    ],
)
def test_looks_like_stub_keeps_single_line_implementations(snippet):
    assert _looks_like_stub(snippet) is False


@pytest.mark.parametrize(
    "snippet",
    [
        "def pending(): pass",
        "def pending(): ...",
        "def pending(): raise NotImplementedError",
        'function pending() { throw new Error("not implemented"); }',
    ],
)
def test_looks_like_stub_detects_single_line_stubs(snippet):
    assert _looks_like_stub(snippet) is True


def test_real_password_implementation_is_not_stub_and_is_confirmed():
    capability = FunctionalCapability(
        capability_id="symbol:authenticate",
        name="authenticate",
        kind="function",
        description="Autentica usuarios con nombre y contraseña.",
        detection="observed",
        evidence=[
            EvidenceLocation(
                file_path="src/auth.py",
                start_line=3,
                end_line=4,
                symbol="authenticate",
                snippet=(
                    "def authenticate(username, password):\n"
                    "    return check_password(username, password)"
                ),
            )
        ],
    )

    assert is_stub_capability(capability) is False

    findings = {
        finding.attribute: finding
        for finding in evaluate_capabilities([capability])
    }
    assert findings["completitud"].classification == "confirmado"
    assert findings["correccion"].classification == "confirmado"
