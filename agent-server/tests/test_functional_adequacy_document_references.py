"""Pruebas de referencias documentales de hallazgos exploratorios (EP-004)."""

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from server.agents.functional_adequacy.agent import FunctionalAdequacyAgent
from server.agents.functional_adequacy.config import FunctionalAdequacyConfig
from server.agents.functional_adequacy.exploratory import (
    evaluate_capabilities,
    extract_document_references,
)
from server.agents.functional_adequacy.repository_adapter import (
    prepare_repository_input,
)
from server.agents.functional_adequacy.schemas import (
    CapabilityCall,
    DocumentReference,
    EvidenceLocation,
    FunctionalCapability,
)


class FakeModel:
    pass


def build_agent():
    agent = FunctionalAdequacyAgent.__new__(FunctionalAdequacyAgent)
    agent.model = FakeModel()
    agent.config = FunctionalAdequacyConfig()
    agent._graph = agent._build_graph()
    return agent


def make_file(
    path,
    content,
    language="markdown",
    status="processed",
    file_id=None,
):
    return SimpleNamespace(
        id=file_id or f"file:{path}",
        path=path,
        language=language,
        status=status,
        content=content,
    )


def make_capability(name, snippet):
    return FunctionalCapability(
        capability_id=f"symbol:{name}",
        name=name,
        kind="function",
        description=f"Símbolo function '{name}'.",
        detection="observed",
        evidence=[
            EvidenceLocation(
                file_path="src/service.py",
                start_line=1,
                end_line=3,
                symbol=name,
                snippet=snippet,
            )
        ],
    )


def test_document_reference_found_in_markdown_heading():
    snapshot = SimpleNamespace(
        files=[
            make_file(
                "docs/requirements.md",
                "# Requisitos\n\n"
                "## REQ-02: Consultar productos por ID\n\n"
                "La API debe permitir consultar un producto.\n",
            )
        ]
    )

    references = extract_document_references(snapshot)

    assert references == [
        DocumentReference(
            requirement_id="REQ-02",
            document_path="docs/requirements.md",
            start_line=3,
            end_line=5,
            title="Consultar productos por ID",
            reference_kind="definition",
        )
    ]


def test_missing_requirement_identifier_leaves_references_empty():
    index = [
        DocumentReference(
            requirement_id="REQ-02",
            document_path="docs/requirements.md",
            start_line=3,
            end_line=5,
        )
    ]
    capability = make_capability(
        "get_product",
        'def get_product(product_id):\n    """REQ-09: sin documentación."""\n'
        "    return None",
    )

    findings = evaluate_capabilities(
        [capability],
        document_references=index,
    )

    assert len(findings) == 3
    assert all(
        finding.document_references == [] for finding in findings
    )


def test_repository_without_documents_leaves_references_empty():
    snapshot = SimpleNamespace(
        files=[
            make_file(
                "src/service.py",
                "def get_product(product_id):\n    return None\n",
                language="python",
            )
        ]
    )

    assert extract_document_references(snapshot) == []


def test_duplicated_identifier_across_documents_keeps_all_references():
    # El snapshot real entrega los archivos ordenados por ruta.
    snapshot = SimpleNamespace(
        files=[
            make_file(
                "README.md",
                "## REQ-02: Consultar (resumen)\n\nResumen.\n",
            ),
            make_file(
                "docs/requirements.md",
                "## REQ-02: Consultar\n\nCuerpo.\n",
            ),
        ]
    )

    references = extract_document_references(snapshot)

    assert [
        (item.requirement_id, item.document_path, item.start_line, item.end_line)
        for item in references
    ] == [
        ("REQ-02", "README.md", 1, 3),
        ("REQ-02", "docs/requirements.md", 1, 3),
    ]


def test_document_reference_lines_match_document_content():
    content = (
        "# Requisitos\n"
        "\n"
        "## REQ-02: Consultar\n"
        "\n"
        "Detalle del requisito.\n"
        "\n"
        "## REQ-03: Crear\n"
        "\n"
        "| REQ-02 | Consulta ya descrita |\n"
    )
    lines = content.splitlines()

    def line_of(needle):
        return next(
            index
            for index, line in enumerate(lines, start=1)
            if needle in line
        )

    references = extract_document_references(
        SimpleNamespace(files=[make_file("docs/requirements.md", content)])
    )

    heading = next(
        item
        for item in references
        if item.requirement_id == "REQ-02"
        and item.start_line == line_of("## REQ-02")
    )
    assert (heading.start_line, heading.end_line) == (
        line_of("## REQ-02"),
        line_of("## REQ-03") - 1,
    )
    assert heading.title == "Consultar"

    mention = next(
        item
        for item in references
        if item.requirement_id == "REQ-03"
    )
    # La fila posterior no es un encabezado, por lo que cierra la sección
    # al final del documento.
    assert (mention.start_line, mention.end_line) == (
        line_of("## REQ-03"),
        len(lines),
    )

    row = next(
        item
        for item in references
        if item.requirement_id == "REQ-02"
        and item.start_line == line_of("| REQ-02 |")
    )
    assert (row.start_line, row.end_line) == (
        line_of("| REQ-02 |"),
        line_of("| REQ-02 |"),
    )
    assert row.title is None


def test_finding_without_requirement_identifiers_has_no_references():
    index = [
        DocumentReference(
            requirement_id="REQ-02",
            document_path="docs/requirements.md",
            start_line=3,
            end_line=5,
        )
    ]
    capability = make_capability(
        "list_products",
        "def list_products():\n    return []\n",
    )

    findings = evaluate_capabilities(
        [capability],
        document_references=index,
    )

    assert len(findings) == 3
    assert all(
        finding.document_references == [] for finding in findings
    )


def test_exploratory_findings_carry_document_references_and_keep_evidence(
    tmp_path,
):
    repository = tmp_path / "demo"
    (repository / "src").mkdir(parents=True)
    (repository / "docs").mkdir(parents=True)
    (repository / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nrequires-python = ">=3.11"\n',
        encoding="utf-8",
    )
    (repository / "src" / "service.py").write_text(
        "class InventoryService:\n"
        "    def get_product(self, product_id):\n"
        '        """REQ-02: obtiene un producto por su identificador."""\n'
        "        return None\n",
        encoding="utf-8",
    )
    (repository / "docs" / "requirements.md").write_text(
        "# Requisitos\n\n"
        "## REQ-02: Consultar productos por ID\n\n"
        "La API debe permitir consultar un producto concreto.\n",
        encoding="utf-8",
    )

    prepared = asyncio.run(prepare_repository_input(repository, []))

    async def unexpected_generate(*args, **kwargs):
        raise AssertionError("El modelo no debe ejecutarse")

    with patch(
        "server.agents.functional_adequacy.agent.traced_generate",
        new=unexpected_generate,
    ):
        output = asyncio.run(build_agent().run(prepared))

    finding = next(
        finding
        for finding in output.findings
        if finding.capability_name == "InventoryService.get_product"
        and finding.attribute == "completitud"
    )

    assert finding.document_references == [
        DocumentReference(
            requirement_id="REQ-02",
            document_path="docs/requirements.md",
            start_line=3,
            end_line=5,
            title="Consultar productos por ID",
            reference_kind="definition",
        )
    ]
    assert finding.evidence
    assert any(
        evidence.file_path == "src/service.py"
        and "REQ-02: obtiene un producto" in (evidence.snippet or "")
        for evidence in finding.evidence
    )


def test_endpoint_inherits_document_references_through_implemented_calls():
    references = [
        DocumentReference(
            requirement_id="REQ-03",
            document_path="docs/requirements.md",
            start_line=3,
            end_line=5,
            title="Crear productos con validación",
        )
    ]
    service = FunctionalCapability(
        capability_id="symbol:InventoryService.create_product",
        name="InventoryService.create_product",
        kind="method",
        description="Símbolo method 'InventoryService.create_product'.",
        detection="observed",
        evidence=[
            EvidenceLocation(
                file_path="src/service.py",
                start_line=32,
                end_line=63,
                symbol="InventoryService.create_product",
                snippet=(
                    'def create_product(self):\n    """REQ-03: crea un producto."""\n'
                    "    return None"
                ),
            )
        ],
    )
    endpoint = FunctionalCapability(
        capability_id="entrypoint:create_product",
        name="create_product",
        kind="http_endpoint",
        description="Punto de entrada http_endpoint POST /products.",
        detection="observed",
        evidence=[
            EvidenceLocation(
                file_path="src/api.py",
                start_line=75,
                end_line=89,
                symbol="create_app.create_product",
                snippet=(
                    "def create_product():\n"
                    "    return service.create_product()\n"
                ),
            )
        ],
        calls=[
            CapabilityCall(
                target_capability_id="symbol:InventoryService.create_product",
                target_symbol="InventoryService.create_product",
                file_path="src/api.py",
                start_line=82,
                end_line=82,
                snippet="    return service.create_product()",
            )
        ],
    )

    findings = evaluate_capabilities(
        [endpoint, service],
        document_references=references,
    )

    endpoint_findings = [
        finding
        for finding in findings
        if finding.capability_id == "entrypoint:create_product"
    ]
    assert len(endpoint_findings) == 3
    assert all(
        finding.document_references == references for finding in endpoint_findings
    )


def test_document_reference_kinds_are_classified():
    snapshot = SimpleNamespace(
        files=[
            make_file(
                "docs/requirements.md",
                "# Requisitos\n\n## REQ-03: Crear productos\nEl sistema debe crear productos.\n",
            ),
            make_file(
                "README.md",
                "| POST | `/products` | REQ-03 |\nUna mención inline de REQ-03 fuera de encabezados.\n",
            ),
        ]
    )

    references = extract_document_references(snapshot)

    assert [reference.reference_kind for reference in references] == [
        "definition",
        "mapping",
        "mention",
    ]
    assert [reference.requirement_id for reference in references] == ["REQ-03"] * 3


def test_findings_are_sorted_definition_first():
    service = FunctionalCapability(
        capability_id="symbol:InventoryService.create_product",
        name="InventoryService.create_product",
        kind="method",
        description="Símbolo method 'InventoryService.create_product'.",
        detection="observed",
        evidence=[
            EvidenceLocation(
                file_path="src/service.py",
                start_line=32,
                end_line=33,
                symbol="InventoryService.create_product",
                snippet='def create_product(self):\n    """REQ-03: crea un producto."""',
            )
        ],
    )
    endpoint = FunctionalCapability(
        capability_id="entrypoint:create_product",
        name="create_product",
        kind="http_endpoint",
        description="Punto de entrada http_endpoint POST /products.",
        detection="observed",
        evidence=[
            EvidenceLocation(
                file_path="src/api.py",
                start_line=75,
                end_line=75,
                symbol="create_app.create_product",
                snippet="def create_product():\n",
            )
        ],
        calls=[
            CapabilityCall(
                target_capability_id=service.capability_id,
                target_symbol="InventoryService.create_product",
                file_path="src/api.py",
                start_line=82,
                end_line=82,
                snippet="    return service.create_product()",
            )
        ],
    )
    references = [
        DocumentReference(
            requirement_id="REQ-03",
            document_path="README.md",
            start_line=2,
            end_line=2,
            reference_kind="mention",
        ),
        DocumentReference(
            requirement_id="REQ-03",
            document_path="docs/requirements.md",
            start_line=3,
            end_line=4,
            reference_kind="definition",
            title="Crear productos",
        ),
        DocumentReference(
            requirement_id="REQ-03",
            document_path="README.md",
            start_line=1,
            end_line=1,
            reference_kind="mapping",
        ),
    ]

    findings = evaluate_capabilities([endpoint, service], document_references=references)

    endpoint_finding = next(
        finding
        for finding in findings
        if finding.capability_id == "entrypoint:create_product"
        and finding.attribute == "correccion"
    )
    assert [
        reference.reference_kind
        for reference in endpoint_finding.document_references
    ] == ["definition", "mapping", "mention"]
