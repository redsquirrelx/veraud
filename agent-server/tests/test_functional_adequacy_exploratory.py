"""Pruebas del modo exploratorio de Adecuación Funcional."""

import asyncio
import json
import textwrap
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


def make_delegating_repository(
    root: Path,
    method_body: str,
    method_name: str = "load",
    call_expression: str | None = None,
) -> Path:
    call = call_expression or f"service.{method_name}(1)"
    return write_repository(
        root,
        {
            "pyproject.toml": (
                '[project]\nname = "demo"\nrequires-python = ">=3.11"\n'
                'dependencies = ["fastapi>=0.100"]\n'
            ),
            "src/service.py": (
                "class InventoryService:\n"
                f"    def {method_name}(self, value):\n"
                f"{textwrap.indent(method_body, '        ')}\n"
            ),
            "src/api.py": (
                "from fastapi import FastAPI\n"
                "from .service import InventoryService\n\n"
                "app = FastAPI()\n\n"
                '@app.get("/items")\n'
                "def list_items():\n"
                "    service = InventoryService()\n"
                f"    return {call}\n"
            ),
        },
    )


def findings_by_capability(output):
    return {
        (finding.capability_name, finding.attribute): finding
        for finding in output.findings
    }


def called_target_files(output, capability):
    capabilities_by_id = {
        item.capability_id: item for item in output.capabilities
    }
    targets = [
        capabilities_by_id.get(call.target_capability_id)
        for call in capability.calls
    ]
    return {
        evidence.file_path
        for target in targets
        if target is not None
        for evidence in target.evidence
    }


def make_method_chain_repository(
    root: Path,
    methods: dict[str, str],
    call_expression: str = "service.process(value)",
) -> Path:
    service_lines = ["class InventoryService:"]
    for method_name, method_body in methods.items():
        service_lines.append(f"    def {method_name}(self, value):")
        service_lines.append(textwrap.indent(method_body, "        "))
    return write_repository(
        root,
        {
            "pyproject.toml": (
                '[project]\nname = "demo"\nrequires-python = ">=3.11"\n'
                'dependencies = ["fastapi>=0.100"]\n'
            ),
            "src/service.py": "\n".join(service_lines) + "\n",
            "src/api.py": (
                "from fastapi import FastAPI\n"
                "from .service import InventoryService\n\n"
                "app = FastAPI()\n\n"
                '@app.get("/items")\n'
                "def list_items():\n"
                "    service = InventoryService()\n"
                f"    return {call_expression}\n"
            ),
        },
    )


def make_temporal_type_repository(
    root: Path,
    endpoint_body: str,
    inventory_body: str = "return value",
    other_body: str = "return value",
) -> Path:
    return write_repository(
        root,
        {
            "pyproject.toml": (
                '[project]\nname = "demo"\nrequires-python = ">=3.11"\n'
                'dependencies = ["fastapi>=0.100"]\n'
            ),
            "src/service.py": (
                "class InventoryService:\n"
                "    def load(self, value):\n"
                f"{textwrap.indent(inventory_body, '        ')}\n\n"
                "class OtherService:\n"
                "    def load(self, value):\n"
                f"{textwrap.indent(other_body, '        ')}\n"
            ),
            "src/api.py": (
                "from fastapi import FastAPI\n"
                "from .service import InventoryService, OtherService\n\n"
                "app = FastAPI()\n\n"
                '@app.get("/items")\n'
                "def list_items(flag=None):\n"
                f"{textwrap.indent(endpoint_body, '    ')}\n"
            ),
        },
    )


def make_scoped_import_repository(
    root: Path,
    imports: str,
    endpoint_body: str,
    *,
    endpoint_params: str = "",
    service_source: str = "def load(value):\n    return value",
    other_source: str = "def load(value):\n    return value",
    extra_api_body: str = "",
) -> Path:
    extra_api = f"\n\n{extra_api_body}\n" if extra_api_body else ""
    return write_repository(
        root,
        {
            "pyproject.toml": (
                '[project]\nname = "demo"\nrequires-python = ">=3.11"\n'
                'dependencies = ["fastapi>=0.100"]\n'
            ),
            "src/__init__.py": "",
            "src/service.py": f"{service_source}\n",
            "src/other.py": f"{other_source}\n",
            "src/api.py": (
                "from fastapi import FastAPI\n"
                f"{imports}\n\n"
                "app = FastAPI()\n\n"
                '@app.get("/items")\n'
                f"def endpoint({endpoint_params}):\n"
                f"{textwrap.indent(endpoint_body, '    ')}"
                f"{extra_api}"
            ),
        },
    )


def run_exploratory_without_model(repository: Path):
    prepared = asyncio.run(prepare_repository_input(repository, []))

    async def unexpected_generate(*args, **kwargs):
        raise AssertionError("El modelo no debe ejecutarse")

    with patch(
        "server.agents.functional_adequacy.agent.traced_generate",
        new=unexpected_generate,
    ):
        return asyncio.run(build_agent().run(prepared))


def line_number_of(repository: Path, relative_path: str, needle: str) -> int:
    lines = (repository / relative_path).read_text(encoding="utf-8").splitlines()
    return next(
        index
        for index, line in enumerate(lines, start=1)
        if needle in line
    )


@pytest.mark.parametrize(
    "method_body",
    [
        'raise NotImplementedError("pendiente")',
        "pass",
        "...",
    ],
)
def test_endpoint_delegating_to_incomplete_method_is_not_confirmed(
    tmp_path,
    method_body,
):
    repository = make_delegating_repository(
        tmp_path / "demo",
        method_body,
    )
    prepared = asyncio.run(prepare_repository_input(repository, []))

    async def unexpected_generate(*args, **kwargs):
        raise AssertionError("El modelo no debe ejecutarse")

    with patch(
        "server.agents.functional_adequacy.agent.traced_generate",
        new=unexpected_generate,
    ):
        output = asyncio.run(build_agent().run(prepared))

    endpoint = next(
        capability
        for capability in output.capabilities
        if capability.name == "list_items"
    )
    assert any(
        call.target_symbol == "InventoryService.load"
        for call in endpoint.calls
    )
    assert any(
        relationship.startswith("invoca: InventoryService.load")
        for relationship in endpoint.relationships
    )

    findings = findings_by_capability(output)
    completeness = findings[("list_items", "completitud")]
    correction = findings[("list_items", "correccion")]
    assert completeness.classification == "probable"
    assert correction.classification == "no_verificado"
    assert "InventoryService.load" in completeness.justification
    assert "InventoryService.load" in correction.justification
    assert any(
        evidence.symbol == "InventoryService.load"
        and evidence.file_path == "src/service.py"
        for evidence in correction.evidence
    )
    assert findings[("InventoryService.load", "completitud")].classification == (
        "probable"
    )
    assert findings[("InventoryService.load", "correccion")].classification == (
        "no_verificado"
    )


def test_endpoint_propagates_to_private_incomplete_method(tmp_path):
    repository = make_delegating_repository(
        tmp_path / "demo",
        'raise NotImplementedError("pendiente")',
        method_name="_load",
    )
    output = run_exploratory_without_model(repository)
    endpoint = next(
        capability
        for capability in output.capabilities
        if capability.name == "list_items"
    )

    assert [call.target_symbol for call in endpoint.calls] == [
        "InventoryService._load"
    ]
    assert any(
        relationship.startswith("invoca: InventoryService._load")
        for relationship in endpoint.relationships
    )

    findings = findings_by_capability(output)
    completeness = findings[("list_items", "completitud")]
    correction = findings[("list_items", "correccion")]
    assert completeness.classification == "probable"
    assert correction.classification == "no_verificado"
    assert "InventoryService._load" in completeness.justification
    assert "InventoryService._load" in correction.justification

    call_line = line_number_of(
        repository,
        "src/api.py",
        "service._load(1)",
    )
    method_line = line_number_of(
        repository,
        "src/service.py",
        'raise NotImplementedError("pendiente")',
    )
    assert any(
        evidence.file_path == "src/api.py"
        and evidence.symbol == "list_items"
        for evidence in endpoint.evidence
    )
    assert any(
        evidence.file_path == "src/api.py"
        and evidence.symbol == "InventoryService._load"
        and evidence.start_line == call_line
        and "service._load(1)" in (evidence.snippet or "")
        for evidence in correction.evidence
    )
    assert any(
        evidence.file_path == "src/service.py"
        and evidence.symbol == "InventoryService._load"
        and evidence.start_line is not None
        and evidence.start_line <= method_line <= (
            evidence.end_line or evidence.start_line
        )
        and "raise NotImplementedError" in (evidence.snippet or "")
        for evidence in correction.evidence
    )


def test_missing_method_does_not_resolve_to_unrelated_skeleton(tmp_path):
    repository = make_delegating_repository(
        tmp_path / "demo",
        'raise NotImplementedError("pendiente")',
        call_expression="service.missing(1)",
    )
    output = run_exploratory_without_model(repository)
    endpoint = next(
        capability
        for capability in output.capabilities
        if capability.name == "list_items"
    )

    assert endpoint.calls == []
    assert not any(
        relationship.startswith("invoca:")
        for relationship in endpoint.relationships
    )

    findings = findings_by_capability(output)
    completeness = findings[("list_items", "completitud")]
    correction = findings[("list_items", "correccion")]
    assert completeness.classification == "confirmado"
    assert correction.classification == "confirmado"
    assert not any(
        evidence.symbol == "InventoryService.load"
        for evidence in correction.evidence
    )


def test_import_without_real_call_does_not_confirm_or_propagate(tmp_path):
    repository = write_repository(
        tmp_path / "demo",
        {
            "pyproject.toml": (
                '[project]\nname = "demo"\nrequires-python = ">=3.11"\n'
                'dependencies = ["fastapi>=0.100"]\n'
            ),
            "src/service.py": (
                "class InventoryService:\n"
                "    def load(self, value):\n"
                '        raise NotImplementedError("pendiente")\n'
            ),
            "src/module.py": (
                "from .service import InventoryService\n\n"
                "def wrapper():\n"
                "    return 1\n"
            ),
            "src/api.py": (
                "from fastapi import FastAPI\n"
                "from .service import InventoryService\n\n"
                "app = FastAPI()\n\n"
                '@app.get("/items")\n'
                "def list_items():\n"
                "    return []\n"
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

    wrapper = next(
        capability
        for capability in output.capabilities
        if capability.name == "wrapper"
    )
    endpoint = next(
        capability
        for capability in output.capabilities
        if capability.name == "list_items"
    )
    assert wrapper.calls == []
    assert endpoint.calls == []
    assert any(
        relationship.startswith("importa: .service")
        for relationship in wrapper.relationships
    )
    assert not any(
        relationship.startswith("invoca:")
        for relationship in wrapper.relationships
    )
    assert not any(
        relationship.startswith("invoca:")
        for relationship in endpoint.relationships
    )

    findings = findings_by_capability(output)
    assert findings[("wrapper", "pertinencia")].classification == "probable"
    assert findings[("list_items", "completitud")].classification == (
        "confirmado"
    )
    assert findings[("list_items", "correccion")].classification == (
        "confirmado"
    )


def test_imported_function_call_resolves_to_source_module(tmp_path):
    repository = make_scoped_import_repository(
        tmp_path / "demo",
        "from .service import load",
        "return load(1)",
        service_source='def load(value):\n    raise NotImplementedError("pendiente")',
    )
    output = run_exploratory_without_model(repository)
    endpoint = next(
        capability
        for capability in output.capabilities
        if capability.name == "endpoint"
    )

    assert called_target_files(output, endpoint) == {"src/service.py"}
    findings = findings_by_capability(output)
    assert findings[("endpoint", "completitud")].classification == "probable"
    assert findings[("endpoint", "correccion")].classification == (
        "no_verificado"
    )


def test_import_alias_resolves_to_original_imported_name(tmp_path):
    repository = make_scoped_import_repository(
        tmp_path / "demo",
        "from .service import load as service_load",
        "return service_load(1)",
        service_source='def load(value):\n    raise NotImplementedError("pendiente")',
    )
    output = run_exploratory_without_model(repository)
    endpoint = next(
        capability
        for capability in output.capabilities
        if capability.name == "endpoint"
    )

    assert [call.target_symbol for call in endpoint.calls] == ["load"]
    assert called_target_files(output, endpoint) == {"src/service.py"}
    findings = findings_by_capability(output)
    assert findings[("endpoint", "completitud")].classification == "probable"
    assert findings[("endpoint", "correccion")].classification == (
        "no_verificado"
    )


def test_local_function_shadows_imported_function(tmp_path):
    repository = make_scoped_import_repository(
        tmp_path / "demo",
        "from .service import load",
        (
            "def load():\n"
            "    return 1\n"
            "\n"
            "return load()\n"
        ),
        service_source='def load(value):\n    raise NotImplementedError("pendiente")',
    )
    output = run_exploratory_without_model(repository)
    endpoint = next(
        capability
        for capability in output.capabilities
        if capability.name == "endpoint"
    )

    assert called_target_files(output, endpoint) == {"src/api.py"}
    findings = findings_by_capability(output)
    assert findings[("endpoint", "completitud")].classification == (
        "confirmado"
    )
    assert findings[("endpoint", "correccion")].classification == (
        "confirmado"
    )


def test_parameter_shadows_imported_function(tmp_path):
    repository = make_scoped_import_repository(
        tmp_path / "demo",
        "from .service import load",
        "return load(1)",
        endpoint_params="load",
        service_source='def load(value):\n    raise NotImplementedError("pendiente")',
    )
    output = run_exploratory_without_model(repository)
    endpoint = next(
        capability
        for capability in output.capabilities
        if capability.name == "endpoint"
    )

    assert endpoint.calls == []
    findings = findings_by_capability(output)
    assert findings[("endpoint", "completitud")].classification == (
        "confirmado"
    )
    assert findings[("endpoint", "correccion")].classification == (
        "confirmado"
    )


def test_local_variable_shadows_imported_function(tmp_path):
    repository = make_scoped_import_repository(
        tmp_path / "demo",
        "from .service import load",
        (
            "load = get_local_handler()\n"
            "return load(1)\n"
        ),
        service_source='def load(value):\n    raise NotImplementedError("pendiente")',
    )
    output = run_exploratory_without_model(repository)
    endpoint = next(
        capability
        for capability in output.capabilities
        if capability.name == "endpoint"
    )

    assert endpoint.calls == []
    findings = findings_by_capability(output)
    assert findings[("endpoint", "completitud")].classification == (
        "confirmado"
    )
    assert findings[("endpoint", "correccion")].classification == (
        "confirmado"
    )


def test_local_import_does_not_leak_to_other_functions(tmp_path):
    repository = make_scoped_import_repository(
        tmp_path / "demo",
        "",
        (
            "from .service import load\n"
            "return load(1)\n"
        ),
        service_source='def load(value):\n    raise NotImplementedError("pendiente")',
        extra_api_body=(
            "def other():\n"
            "    return load(1)\n"
        ),
    )
    output = run_exploratory_without_model(repository)
    endpoint = next(
        capability
        for capability in output.capabilities
        if capability.name == "endpoint"
    )
    other = next(
        capability
        for capability in output.capabilities
        if capability.name == "other"
    )

    assert called_target_files(output, endpoint) == {"src/service.py"}
    assert other.calls == []
    findings = findings_by_capability(output)
    assert findings[("endpoint", "completitud")].classification == "probable"
    assert findings[("other", "completitud")].classification == "confirmado"
    assert findings[("other", "correccion")].classification == "confirmado"


def test_homonymous_functions_resolve_by_imported_module(tmp_path):
    repository = make_scoped_import_repository(
        tmp_path / "demo",
        "from .service import load",
        "return load(1)",
        service_source='def load(value):\n    raise NotImplementedError("pendiente")',
        other_source="def load(value):\n    return value",
    )
    output = run_exploratory_without_model(repository)
    endpoint = next(
        capability
        for capability in output.capabilities
        if capability.name == "endpoint"
    )

    assert called_target_files(output, endpoint) == {"src/service.py"}
    findings = findings_by_capability(output)
    assert findings[("endpoint", "completitud")].classification == "probable"
    assert findings[("endpoint", "correccion")].classification == (
        "no_verificado"
    )


def test_module_level_function_shadows_imported_function(tmp_path):
    repository = make_scoped_import_repository(
        tmp_path / "demo",
        "from .service import load",
        "return load(1)",
        service_source='def load(value):\n    raise NotImplementedError("pendiente")',
        extra_api_body=(
            "def load(value):\n"
            "    return value\n"
        ),
    )
    output = run_exploratory_without_model(repository)
    endpoint = next(
        capability
        for capability in output.capabilities
        if capability.name == "endpoint"
    )

    assert called_target_files(output, endpoint) == {"src/api.py"}
    findings = findings_by_capability(output)
    assert findings[("endpoint", "completitud")].classification == (
        "confirmado"
    )
    assert findings[("endpoint", "correccion")].classification == (
        "confirmado"
    )


def test_endpoint_delegating_to_implemented_method_remains_confirmed(tmp_path):
    repository = make_delegating_repository(
        tmp_path / "demo",
        "return value + 1",
    )
    prepared = asyncio.run(prepare_repository_input(repository, []))

    async def unexpected_generate(*args, **kwargs):
        raise AssertionError("El modelo no debe ejecutarse")

    with patch(
        "server.agents.functional_adequacy.agent.traced_generate",
        new=unexpected_generate,
    ):
        output = asyncio.run(build_agent().run(prepared))

    endpoint = next(
        capability
        for capability in output.capabilities
        if capability.name == "list_items"
    )
    method = next(
        capability
        for capability in output.capabilities
        if capability.name == "InventoryService.load"
    )
    assert any(
        call.target_symbol == "InventoryService.load"
        for call in endpoint.calls
    )
    assert any(
        relationship.startswith("invoca: InventoryService.load")
        for relationship in endpoint.relationships
    )

    findings = findings_by_capability(output)
    assert findings[("list_items", "completitud")].classification == (
        "confirmado"
    )
    assert findings[("list_items", "correccion")].classification == (
        "confirmado"
    )
    assert findings[("InventoryService.load", "completitud")].classification == (
        "confirmado"
    )
    assert findings[("InventoryService.load", "correccion")].classification == (
        "confirmado"
    )
    assert method.calls == []


def test_ambiguous_call_is_not_propagated(tmp_path):
    repository = write_repository(
        tmp_path / "demo",
        {
            "pyproject.toml": (
                '[project]\nname = "demo"\nrequires-python = ">=3.11"\n'
                'dependencies = ["fastapi>=0.100"]\n'
            ),
            "src/services.py": (
                "class First:\n"
                "    def process(self):\n"
                "        return 1\n\n"
                "class Second:\n"
                "    def process(self):\n"
                '        raise NotImplementedError("pendiente")\n'
            ),
            "src/api.py": (
                "from fastapi import FastAPI\n"
                "from .services import First, Second\n\n"
                "app = FastAPI()\n\n"
                '@app.get("/ambiguous")\n'
                "def handle(service):\n"
                "    return service.process()\n"
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

    endpoint = next(
        capability
        for capability in output.capabilities
        if capability.name == "handle"
    )
    assert endpoint.calls == []
    assert not any(
        relationship.startswith("invoca:")
        for relationship in endpoint.relationships
    )

    findings = findings_by_capability(output)
    assert findings[("handle", "completitud")].classification == "confirmado"
    assert findings[("handle", "correccion")].classification == "confirmado"


def test_endpoint_propagates_through_implemented_intermediate_method(tmp_path):
    repository = make_method_chain_repository(
        tmp_path / "demo",
        {
            "load": 'raise NotImplementedError("pendiente")',
            "process": "return self.load(value)",
        },
    )
    output = run_exploratory_without_model(repository)
    endpoint = next(
        capability
        for capability in output.capabilities
        if capability.name == "list_items"
    )
    process = next(
        capability
        for capability in output.capabilities
        if capability.name == "InventoryService.process"
    )

    findings = findings_by_capability(output)
    for capability_name in (
        "list_items",
        "InventoryService.process",
    ):
        completeness = findings[(capability_name, "completitud")]
        correction = findings[(capability_name, "correccion")]
        assert completeness.classification == "probable"
        assert correction.classification == "no_verificado"
        assert "InventoryService.load" in completeness.justification
        assert "InventoryService.load" in correction.justification

    assert findings[("InventoryService.load", "completitud")].classification == (
        "probable"
    )
    assert findings[("InventoryService.load", "correccion")].classification == (
        "no_verificado"
    )

    assert any(
        call.target_symbol == "InventoryService.process"
        for call in endpoint.calls
    )
    assert any(
        call.target_symbol == "InventoryService.load"
        for call in process.calls
    )
    assert any(
        evidence.symbol == "InventoryService.load"
        and evidence.file_path == "src/service.py"
        for evidence in findings[
            ("InventoryService.process", "correccion")
        ].evidence
    )


def test_endpoint_propagates_through_multiple_levels_with_full_evidence(
    tmp_path,
):
    repository = make_method_chain_repository(
        tmp_path / "demo",
        {
            "load": 'raise NotImplementedError("pendiente")',
            "normalize": "return self.load(value)",
            "process": "return self.normalize(value)",
        },
    )
    output = run_exploratory_without_model(repository)
    endpoint = next(
        capability
        for capability in output.capabilities
        if capability.name == "list_items"
    )
    process = next(
        capability
        for capability in output.capabilities
        if capability.name == "InventoryService.process"
    )
    normalize = next(
        capability
        for capability in output.capabilities
        if capability.name == "InventoryService.normalize"
    )

    findings = findings_by_capability(output)
    for capability_name in (
        "list_items",
        "InventoryService.process",
        "InventoryService.normalize",
    ):
        completeness = findings[(capability_name, "completitud")]
        correction = findings[(capability_name, "correccion")]
        assert completeness.classification == "probable"
        assert correction.classification == "no_verificado"
        assert "InventoryService.load" in completeness.justification

    assert (
        "InventoryService.process -> InventoryService.normalize -> "
        "InventoryService.load"
    ) in findings[("list_items", "completitud")].justification
    assert (
        "InventoryService.normalize -> InventoryService.load"
    ) in findings[("InventoryService.process", "completitud")].justification

    assert any(
        call.target_symbol == "InventoryService.process"
        for call in endpoint.calls
    )
    assert any(
        call.target_symbol == "InventoryService.normalize"
        for call in process.calls
    )
    assert any(
        call.target_symbol == "InventoryService.load"
        for call in normalize.calls
    )

    expected_evidence = (
        (
            "src/api.py",
            "InventoryService.process",
            "service.process(value)",
        ),
        (
            "src/service.py",
            "InventoryService.normalize",
            "self.normalize(value)",
        ),
        (
            "src/service.py",
            "InventoryService.load",
            "self.load(value)",
        ),
    )
    endpoint_correction = findings[("list_items", "correccion")]
    for file_path, symbol, needle in expected_evidence:
        expected_line = line_number_of(repository, file_path, needle)
        assert any(
            evidence.file_path == file_path
            and evidence.symbol == symbol
            and evidence.start_line == expected_line
            and needle in (evidence.snippet or "")
            for evidence in endpoint_correction.evidence
        )
    assert any(
        evidence.file_path == "src/service.py"
        and evidence.symbol == "InventoryService.load"
        and "raise NotImplementedError" in (evidence.snippet or "")
        for evidence in endpoint_correction.evidence
    )


def test_cycle_in_resolved_calls_does_not_block_propagation(tmp_path):
    repository = make_method_chain_repository(
        tmp_path / "demo",
        {
            "load": 'raise NotImplementedError("pendiente")',
            "ping": "return self.pong(value)",
            "pong": "self.ping(value)\nreturn self.load(value)",
        },
        call_expression="service.ping(value)",
    )
    output = run_exploratory_without_model(repository)
    endpoint = next(
        capability
        for capability in output.capabilities
        if capability.name == "list_items"
    )
    ping = next(
        capability
        for capability in output.capabilities
        if capability.name == "InventoryService.ping"
    )
    pong = next(
        capability
        for capability in output.capabilities
        if capability.name == "InventoryService.pong"
    )

    findings = findings_by_capability(output)
    for capability_name in (
        "list_items",
        "InventoryService.ping",
        "InventoryService.pong",
    ):
        completeness = findings[(capability_name, "completitud")]
        correction = findings[(capability_name, "correccion")]
        assert completeness.classification == "probable"
        assert correction.classification == "no_verificado"
        assert "InventoryService.load" in completeness.justification

    assert (
        "InventoryService.ping -> InventoryService.pong -> "
        "InventoryService.load"
    ) in findings[("list_items", "completitud")].justification
    assert (
        "InventoryService.pong -> InventoryService.load"
    ) in findings[("InventoryService.ping", "completitud")].justification

    assert any(
        call.target_symbol == "InventoryService.pong"
        for call in ping.calls
    )
    assert any(
        call.target_symbol == "InventoryService.ping"
        for call in pong.calls
    )
    assert any(
        call.target_symbol == "InventoryService.load"
        for call in pong.calls
    )
    assert any(
        call.target_symbol == "InventoryService.ping"
        for call in endpoint.calls
    )


def test_call_uses_type_before_later_reassignment(tmp_path):
    repository = make_temporal_type_repository(
        tmp_path / "demo",
        (
            "service = InventoryService()\n"
            "service.load(1)\n"
            "service = OtherService()\n"
            "return service.load(1)\n"
        ),
        inventory_body='raise NotImplementedError("pendiente")',
    )
    output = run_exploratory_without_model(repository)
    endpoint = next(
        capability
        for capability in output.capabilities
        if capability.name == "list_items"
    )

    assert [call.target_symbol for call in endpoint.calls] == [
        "InventoryService.load",
        "OtherService.load",
    ]

    findings = findings_by_capability(output)
    completeness = findings[("list_items", "completitud")]
    correction = findings[("list_items", "correccion")]
    assert completeness.classification == "probable"
    assert correction.classification == "no_verificado"
    assert "InventoryService.load" in completeness.justification


def test_call_uses_other_type_before_later_reassignment(tmp_path):
    repository = make_temporal_type_repository(
        tmp_path / "demo",
        (
            "service = OtherService()\n"
            "service.load(1)\n"
            "service = InventoryService()\n"
            "return service.load(1)\n"
        ),
        other_body='raise NotImplementedError("pendiente")',
    )
    output = run_exploratory_without_model(repository)
    endpoint = next(
        capability
        for capability in output.capabilities
        if capability.name == "list_items"
    )

    assert [call.target_symbol for call in endpoint.calls] == [
        "OtherService.load",
        "InventoryService.load",
    ]

    findings = findings_by_capability(output)
    completeness = findings[("list_items", "completitud")]
    correction = findings[("list_items", "correccion")]
    assert completeness.classification == "probable"
    assert correction.classification == "no_verificado"
    assert "OtherService.load" in completeness.justification


def test_conditional_types_leave_call_unresolved(tmp_path):
    repository = make_temporal_type_repository(
        tmp_path / "demo",
        (
            "if flag:\n"
            "    service = InventoryService()\n"
            "else:\n"
            "    service = OtherService()\n"
            "return service.load(1)\n"
        ),
        inventory_body='raise NotImplementedError("pendiente")',
    )
    output = run_exploratory_without_model(repository)
    endpoint = next(
        capability
        for capability in output.capabilities
        if capability.name == "list_items"
    )

    assert endpoint.calls == []
    assert not any(
        relationship.startswith("invoca:")
        for relationship in endpoint.relationships
    )

    findings = findings_by_capability(output)
    assert findings[("list_items", "completitud")].classification == (
        "confirmado"
    )
    assert findings[("list_items", "correccion")].classification == (
        "confirmado"
    )


def test_conditional_branches_with_same_type_keep_resolution(tmp_path):
    repository = make_temporal_type_repository(
        tmp_path / "demo",
        (
            "if flag:\n"
            "    service = InventoryService()\n"
            "else:\n"
            "    service = InventoryService()\n"
            "return service.load(1)\n"
        ),
        inventory_body='raise NotImplementedError("pendiente")',
    )
    output = run_exploratory_without_model(repository)
    endpoint = next(
        capability
        for capability in output.capabilities
        if capability.name == "list_items"
    )

    assert [call.target_symbol for call in endpoint.calls] == [
        "InventoryService.load"
    ]

    findings = findings_by_capability(output)
    assert findings[("list_items", "completitud")].classification == (
        "probable"
    )
    assert findings[("list_items", "correccion")].classification == (
        "no_verificado"
    )


def test_unrelated_incomplete_method_does_not_propagate(tmp_path):
    repository = make_method_chain_repository(
        tmp_path / "demo",
        {
            "load": 'raise NotImplementedError("pendiente")',
            "process": "return value + 1",
        },
    )
    output = run_exploratory_without_model(repository)
    endpoint = next(
        capability
        for capability in output.capabilities
        if capability.name == "list_items"
    )
    process = next(
        capability
        for capability in output.capabilities
        if capability.name == "InventoryService.process"
    )

    findings = findings_by_capability(output)
    for capability_name in (
        "list_items",
        "InventoryService.process",
    ):
        assert findings[(capability_name, "completitud")].classification == (
            "confirmado"
        )
        assert findings[(capability_name, "correccion")].classification == (
            "confirmado"
        )
        assert not any(
            evidence.symbol == "InventoryService.load"
            for evidence in findings[
                (capability_name, "correccion")
            ].evidence
        )

    assert findings[("InventoryService.load", "completitud")].classification == (
        "probable"
    )
    assert findings[("InventoryService.load", "correccion")].classification == (
        "no_verificado"
    )
    assert process.calls == []
    assert any(
        call.target_symbol == "InventoryService.process"
        for call in endpoint.calls
    )
