
import asyncio
import json
from unittest.mock import patch

import pytest

from server.agents.functional_adequacy.agent import (
    SBERT_DEPENDENCY_ERROR,
    FunctionalAdequacyAgent,
    SemanticRetrievalUnavailableError,
)
from server.agents.functional_adequacy.schemas import FunctionalAdequacyInput


class FakeModel:
    pass


def build_agent():
    agent = FunctionalAdequacyAgent.__new__(FunctionalAdequacyAgent)
    agent.model = FakeModel()
    agent._graph = agent._build_graph()
    return agent


def require_semantic_retrieval():
    pytest.importorskip("sentence_transformers")


def make_input(requirements, fragments):
    return FunctionalAdequacyInput.model_validate({
        "requirements": requirements,
        "code_fragments": fragments,
    })


def test_allows_missing_requirements():
    data = FunctionalAdequacyInput.model_validate({
        "code_fragments": [],
    })

    assert data.requirements == []


def test_allows_empty_requirements():
    data = FunctionalAdequacyInput.model_validate({
        "requirements": [],
        "code_fragments": [],
    })

    assert data.requirements == []


def test_prepare_selects_requirements_based_mode():
    agent = build_agent()

    data = make_input(
        [{"requirement_id": "REQ-001", "description": "User authentication"}],
        [],
    )

    result = asyncio.run(
        agent._prepare({"input_data": data})
    )

    assert result["audit_mode"] == "requirements_based"


def test_prepare_selects_exploratory_mode_without_requirements():
    agent = build_agent()

    data = FunctionalAdequacyInput.model_validate({
        "code_fragments": [
            {
                "fragment_id": "CODE-001",
                "file_path": "auth.py",
                "code": "def authenticate_user(): return True",
            }
        ]
    })

    result = asyncio.run(
        agent._prepare({"input_data": data})
    )

    assert result["audit_mode"] == "exploratory"

def test_rejects_duplicate_requirement_ids():
    with pytest.raises(ValueError):
        make_input(
            [
                {"requirement_id": "REQ-001", "description": "Login"},
                {"requirement_id": "REQ-001", "description": "Logout"},
            ],
            [],
        )

def test_sbert_retrieves_expected_fragments():
    require_semantic_retrieval()
    data = make_input(
        [
            {
                "requirement_id": "REQ-001",
                "description": "The system must authenticate users using a password.",
            },
            {
                "requirement_id": "REQ-002",
                "description": "The system must calculate the total price of a purchase.",
            },
        ],
        [
            {
                "fragment_id": "CODE-001",
                "file_path": "auth.py",
                "code": "def authenticate_user(username, password): return check_password(username, password)",
            },
            {
                "fragment_id": "CODE-002",
                "file_path": "sales.py",
                "code": "def calculate_total(items): return sum(item.price * item.quantity for item in items)",
            },
            {
                "fragment_id": "CODE-003",
                "file_path": "utils.py",
                "code": "def format_date(date): return date.strftime('%Y-%m-%d')",
            },
        ],
    )

    async def run_mapping():
        state = {"input_data": data}
        state.update(await FunctionalAdequacyAgent._prepare(None, state))
        return await FunctionalAdequacyAgent._code_mapping(None, state)

    result = asyncio.run(run_mapping())
    candidates = result["candidates"]

    assert candidates["REQ-001"][0].fragment_id == "CODE-001"
    assert candidates["REQ-002"][0].fragment_id == "CODE-002"

def test_full_execution_and_coverage():
    require_semantic_retrieval()
    data = make_input(
        [
            {
                "requirement_id": "REQ-001",
                "description": "Authenticate users with passwords.",
            },
            {
                "requirement_id": "REQ-002",
                "description": "Calculate the total price considering quantities.",
            },
            {
                "requirement_id": "REQ-003",
                "description": "Recover forgotten passwords.",
            },
        ],
        [
            {
                "fragment_id": "CODE-001",
                "file_path": "auth.py",
                "code": "def authenticate_user(username, password): return check_password(username, password)",
            },
            {
                "fragment_id": "CODE-002",
                "file_path": "sales.py",
                "code": "def calculate_total(items): return sum(item.price for item in items)",
            },
        ],
    )

    async def fake_generate(model, prompt):
        if "Identificador: REQ-001" in prompt:
            status = "cumple"
        elif "Identificador: REQ-002" in prompt:
            status = "no_cumple"
        else:
            status = "evidencia_insuficiente"

        return json.dumps({
            "status": status,
            "justification": f"Evaluación simulada para {status}.",
        })

    with patch(
        "server.agents.functional_adequacy.agent.traced_generate",
        new=fake_generate,
    ):
        output = asyncio.run(build_agent().run(data))

    assert output.total_requirements == 3
    assert output.fulfilled_requirements == 1
    assert output.score == 33.33
    assert [item.status for item in output.results] == [
        "cumple",
        "no_cumple",
        "evidencia_insuficiente",
    ]
    assert len(output.recommendations) == 2


def test_invalid_llm_response():
    require_semantic_retrieval()
    data = make_input(
        [{"requirement_id": "REQ-001", "description": "Validate passwords."}],
        [{
            "fragment_id": "CODE-001",
            "file_path": "auth.py",
            "code": "def login(password): return True",
        }],
    )

    async def invalid_generate(model, prompt):
        return "Invalid response without JSON"

    with patch(
        "server.agents.functional_adequacy.agent.traced_generate",
        new=invalid_generate,
    ):
        output = asyncio.run(build_agent().run(data))

    assert output.results[0].status == "evidencia_insuficiente"
    assert output.score == 0.0


def test_no_code_skips_sbert_and_llm():
    data = make_input(
        [{"requirement_id": "REQ-001", "description": "Allow login."}],
        [],
    )

    async def unexpected_generate(model, prompt):
        raise AssertionError("LLM should not execute")

    with (
        patch(
            "server.agents.functional_adequacy.agent.traced_generate",
            new=unexpected_generate,
        ),
        patch(
            "server.agents.functional_adequacy.agent._get_sbert_model",
            side_effect=AssertionError("SBERT should not execute"),
        ),
    ):
        output = asyncio.run(build_agent().run(data))

    assert output.score == 0.0
    assert output.results[0].status == "evidencia_insuficiente"
    assert output.results[0].evidence == []


def test_llm_provider_failure():
    require_semantic_retrieval()
    data = make_input(
        [{"requirement_id": "REQ-001", "description": "Validate passwords."}],
        [{
            "fragment_id": "CODE-001",
            "file_path": "auth.py",
            "code": "def validate_password(password): return len(password) >= 8",
        }],
    )

    async def failing_generate(model, prompt):
        raise ConnectionError("LLM provider unavailable")

    with patch(
        "server.agents.functional_adequacy.agent.traced_generate",
        new=failing_generate,
    ):
        output = asyncio.run(build_agent().run(data))

    assert output.results[0].status == "evidencia_insuficiente"
    assert output.score == 0.0
    assert output.fulfilled_requirements == 0

def test_exploratory_mode_does_not_load_semantic_retrieval():
    data = FunctionalAdequacyInput.model_validate({
        "code_fragments": [
            {
                "fragment_id": "CODE-001",
                "file_path": "routes.py:1-3",
                "code": "def list_items():\n    return []\n",
            }
        ]
    })

    with patch(
        "server.agents.functional_adequacy.agent._get_sbert_model",
        side_effect=AssertionError("Exploratory mode must not load SBERT"),
    ):
        output = asyncio.run(build_agent().run(data))

    assert output.audit_mode == "exploratory"
    assert output.score_applicable is False
    assert {item.attribute for item in output.subattributes} == {
        "completitud",
        "correccion",
        "pertinencia",
    }


def test_missing_semantic_retrieval_dependency_returns_controlled_result():
    data = make_input(
        [{"requirement_id": "REQ-001", "description": "Allow login."}],
        [{
            "fragment_id": "CODE-001",
            "file_path": "auth.py",
            "code": "def login(): return True",
        }],
    )

    async def unexpected_generate(model, prompt):
        raise AssertionError("LLM should not execute without evidence")

    with (
        patch(
            "server.agents.functional_adequacy.agent._get_sbert_model",
            side_effect=SemanticRetrievalUnavailableError(
                SBERT_DEPENDENCY_ERROR
            ),
        ),
        patch(
            "server.agents.functional_adequacy.agent.traced_generate",
            new=unexpected_generate,
        ),
    ):
        output = asyncio.run(build_agent().run(data))

    assert output.audit_mode == "requirements_based"
    assert output.score == 0.0
    assert output.results[0].status == "evidencia_insuficiente"
    assert SBERT_DEPENDENCY_ERROR in output.results[0].justification
    assert SBERT_DEPENDENCY_ERROR in output.limitations


def test_explicit_route_symbol_is_retrieved():
    """Verifica que una coincidencia explícita no se pierda por el ranking semántico."""
    pytest.importorskip("torch")
    from unittest.mock import Mock

    import torch

    data = make_input(
        [
            {
                "requirement_id": "REQ-FL-002",
                "description": "Flask debe registrar una ruta HTTP GET mediante app.get.",
            }
        ],
        [
            {
                "fragment_id": f"UNRELATED-{index}",
                "file_path": f"other_{index}.py",
                "code": f"def unrelated_{index}(): return {index}",
            }
            for index in range(5)
        ]
        + [
            {
                "fragment_id": "ROUTE-TEST",
                "file_path": "tests/test_testing.py:175-186",
                "code": '@app.get("/")\ndef index():\n    return "42"',
            }
        ],
    )

    fake_model = Mock()
    fake_model.encode.side_effect = [
        torch.zeros((1, 2)),
        torch.zeros((6, 2)),
    ]

    scores = torch.tensor([[0.9, 0.8, 0.7, 0.6, 0.5, 0.1]])

    async def run_mapping():
        with (
            patch(
                "server.agents.functional_adequacy.agent._get_sbert_model",
                return_value=fake_model,
            ),
            patch(
                "server.agents.functional_adequacy.agent._cosine_similarity",
                return_value=scores,
            ),
        ):
            return await FunctionalAdequacyAgent._code_mapping(
                None, {"input_data": data}
            )

    result = asyncio.run(run_mapping())
    selected_ids = [
        item.fragment_id
        for item in result["candidates"]["REQ-FL-002"]
    ]

    assert "ROUTE-TEST" in selected_ids
