"""HTTP/OpenAPI contracts, with no model calls or callback network traffic."""

import asyncio
import json
from typing import Any

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from openapi_spec_validator import validate
from pydantic import BaseModel

from server.agents.dummy.schemas import DummyInput, DummyOutput, Finding
from server.api.schemas import ExecutionConfig, ExecutionRequest, ModelConfig
from server.app import execution_service
from server.app.agent_registry import UnknownAgentError
from server.app.execution_service import InvalidConfigError, InvalidInputError
from server.main import app


class NestedOutput(BaseModel):
    data: dict[str, Any]


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(execution_service.tracing, "setup", lambda: None)
    service = execution_service.AgentExecutionService()

    class StubService:
        error = None
        result = None
        received = None

        def list_agents(self):
            return service.list_agents()

        def describe_agent(self, name):
            return service.describe_agent(name)

        async def run(self, agent_type, config, payload, execution_id=None, *, blackboard=None):
            self.blackboard = blackboard
            self.received = (agent_type, config.model_dump(), payload, execution_id)
            if self.error is not None:
                raise self.error
            return self.result

    stub = StubService()
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[execution_service.get_execution_service] = lambda: stub
    try:
        with TestClient(app) as client:
            yield client, stub, service
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def assert_response_contract(client, response, path, method):
    spec = client.get("/openapi.json").json()
    schema = spec["paths"][path][method]["responses"][str(response.status_code)][
        "content"
    ]["application/json"]["schema"]
    Draft202012Validator({"components": spec["components"], **schema}).validate(
        response.json()
    )


def test_portal_and_exact_operation_coverage(api):
    client, _, _ = api
    for path in ["/docs", "/redoc", "/openapi.json"]:
        assert client.get(path).status_code == 200
    html = client.get("/docs").text
    assert "Veraud Agent Server API" in html
    assert "url: '/openapi.json'" in html
    for key, value in {
        "docExpansion": "none",
        "deepLinking": True,
        "filter": True,
        "displayRequestDuration": True,
        "operationsSorter": "alpha",
    }.items():
        assert f'"{key}": {json.dumps(value)}' in html

    spec = client.get("/openapi.json").json()
    validate(spec)
    assert spec["openapi"] == "3.1.0"
    assert spec["info"]["title"] == "Veraud Agent Server API"
    assert spec["info"]["version"] == "0.0.0"
    assert [tag["name"] for tag in spec["tags"]] == ["Status", "Audits", "Agents", "Pipelines"]
    assert all(tag["description"] for tag in spec["tags"])
    # No hardcoded host: the document and relative operations use the portal origin.
    assert spec.get("servers", [{"url": "/"}]) == [{"url": "/"}]
    operations = {
        (method.upper(), path)
        for path, item in spec["paths"].items()
        for method in item
        if method
        in {"get", "post", "put", "patch", "delete", "options", "head", "trace"}
    }
    expected = {
        ("GET", "/api/status"),
        ("GET", "/api/agents"),
        ("GET", "/api/agents/{agent_type}/schema"),
        ("POST", "/api/agents/run"),
        ("POST", "/api/agents/verify-access"),
        ("GET", "/api/pipelines"),
        ("POST", "/api/pipelines/{name}/run"),
        ("POST", "/api/audits"),
        ("GET", "/api/audits/{run_id}"),
        ("GET", "/api/audits/{run_id}/report"),
        ("GET", "/api/audits/{run_id}/report.docx"),
    }

    def application_routes(routes):
        for route in routes:
            if isinstance(route, APIRoute):
                yield route
            elif hasattr(route, "original_router"):
                # FastAPI 0.141 keeps included routers lazy in app.routes.
                yield from application_routes(route.original_router.routes)

    registered = {
        (method, route.path)
        for route in application_routes(app.routes)
        if route.include_in_schema
        for method in route.methods
    }
    assert operations == registered == expected
    ids = []
    for method, path in operations:
        operation = spec["paths"][path][method.lower()]
        assert operation["summary"] and operation["description"]
        assert operation["tags"] == (
            ["Status"]
            if path == "/api/status"
            else ["Pipelines"]
            if path.startswith("/api/pipelines")
            else ["Audits"]
            if path.startswith("/api/audits")
            else ["Agents"]
        )
        success = "202" if (method, path) == ("POST", "/api/audits") else "200"
        assert operation["responses"][success]["description"]
        ids.append(operation["operationId"])
    assert len(ids) == len(set(ids))


def test_run_examples_match_registered_agent_inputs(api):
    client, _, service = api
    operation = client.get("/openapi.json").json()["paths"]["/api/agents/run"]["post"]
    examples = operation["requestBody"]["content"]["application/json"]["examples"]
    assert set(examples) == {"dummy"}
    for example in examples.values():
        request = ExecutionRequest.model_validate(example["value"])
        assert request.agent_type in service.list_agents()
        agent_schema = service.describe_agent(request.agent_type)["input_schema"]
        Draft202012Validator(agent_schema).validate(request.input)
        assert request.config.model.provider in {
            "gemini",
            "google",
            "openrouter",
            "openai",
        }


def test_pipeline_contract_preserves_stage_configuration_and_nested_results(api):
    from server.app.pipeline_service import get_generic_pipeline_service

    client, _, _ = api
    seen = []
    output = {"first": {"custom": {"nullable": None, "items": [1, {"extra": True}]}}}

    class Service:
        async def run(self, pipeline_name, input_data, config, stage_configs=None, execution_ids=None, **options):
            from server.app.pipeline_service import UnknownPipelineError

            if pipeline_name != "two-stage":
                raise UnknownPipelineError(f"Unknown pipeline: {pipeline_name!r}")
            seen.append((pipeline_name, stage_configs))
            return output

    configurations = {
        "first": {
            "model": {
                "provider": "google",
                "name": "first-model",
                "temperature": 0.1,
                "max_tokens": 2000,
            },
            "api_key": "first-key",
        },
    }
    app.dependency_overrides[get_generic_pipeline_service] = lambda: Service()
    try:
        path = "/api/pipelines/two-stage/run"
        response = client.post(
            path,
            json={"input": {"root": "/repo"}, "stage_configs": configurations},
        )
        assert response.status_code == 200
        assert response.json() == output
        assert seen[0][0] == "two-stage"
        assert seen[0][1]["first"].api_key == "first-key"
        assert_response_contract(client, response, "/api/pipelines/{name}/run", "post")
        unknown = client.post(
            "/api/pipelines/missing/run",
            json={"input": {"root": "/repo"}},
        )
        assert unknown.status_code == 404
    finally:
        app.dependency_overrides.pop(get_generic_pipeline_service, None)


def test_status_and_list_responses(api):
    client, _, _ = api
    for path, expected in [
        ("/api/status", {"status": "ok", "service": "agent-server"}),
        ("/api/agents", ["dummy"]),
    ]:
        response = client.get(path)
        assert response.status_code == 200
        assert response.json() == expected
        assert_response_contract(client, response, path, "get")


@pytest.mark.parametrize("name", ["dummy"])
def test_agent_schema_response_matches_pydantic_models(api, name):
    client, _, service = api
    agent = service._registry.get(name)
    response = client.get(f"/api/agents/{name}/schema")
    assert response.status_code == 200
    assert response.json() == {
        "agent_type": name,
        "input_schema": agent.input_schema.model_json_schema(),
        "output_schema": agent.output_schema.model_json_schema(),
    }
    for field in ["input_schema", "output_schema"]:
        Draft202012Validator.check_schema(response.json()[field])
    assert_response_contract(client, response, "/api/agents/{agent_type}/schema", "get")


@pytest.mark.parametrize(
    "name,result",
    [
        (
            "dummy",
            DummyOutput(
                evaluated_attribute="maintainability",
                score=90,
                findings=[
                    Finding(
                        title="Example", description="Nested finding", severity="medium"
                    )
                ],
                recommendations=["Document the function"],
            ),
        ),
        (
            "dummy",
            NestedOutput(
                data={
                    "nullable": None,
                    "nested": [{"unknown_field": True}],
                    "empty": [],
                }
            ),
        ),
    ],
)
def test_execution_serialization_preserves_output(api, name, result):
    client, stub, _ = api
    stub.result = result
    response = client.post(
        "/api/agents/run",
        json={
            "agent_type": name,
            "input": {"custom": "forwarded"},
            "config": {"api_key": "test-key"},
            "execution_id": 5,
        },
    )
    assert response.status_code == 200
    assert stub.blackboard is app.state.blackboard
    assert response.json() == {
        "agent_type": name,
        "result": result.model_dump(mode="json"),
    }
    assert stub.received == (
        name,
        {
            "model": {
                "provider": None,
                "name": None,
                "temperature": None,
                "max_tokens": None,
            },
            "timeout_seconds": None,
            "api_key": "test-key",
        },
        {"custom": "forwarded"},
        5,
    )
    assert_response_contract(client, response, "/api/agents/run", "post")


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"agent_type": "dummy", "execution_id": 0},
        {"agent_type": "dummy", "config": None},
        {"agent_type": "dummy", "input": None},
        {"agent_type": "dummy", "config": {"model": None}},
    ],
)
def test_request_validation_422(api, body):
    client, stub, _ = api
    response = client.post("/api/agents/run", json=body)
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert stub.received is None
    assert_response_contract(client, response, "/api/agents/run", "post")


@pytest.mark.parametrize(
    "error,status",
    [
        (UnknownAgentError("Unknown agent: 'missing'"), 404),
        (InvalidConfigError("Unsupported model provider: 'groq'"), 422),
        (InvalidInputError("Invalid input for agent 'dummy'"), 422),
        (FileNotFoundError("Repository path does not exist"), 422),
        (TimeoutError(), 504),
    ],
)
def test_domain_errors_match_documented_responses(api, error, status):
    client, stub, _ = api
    stub.error = error
    response = client.post("/api/agents/run", json={"agent_type": "dummy"})
    assert response.status_code == status
    assert response.json() == {
        "detail": "Agent execution timed out" if status == 504 else str(error)
    }
    assert_response_contract(client, response, "/api/agents/run", "post")


def test_unknown_agent_schema(api):
    client, _, _ = api
    response = client.get("/api/agents/missing/schema")
    assert response.status_code == 404
    assert response.json() == {
        "detail": str(UnknownAgentError("Unknown agent: 'missing'"))
    }
    assert_response_contract(client, response, "/api/agents/{agent_type}/schema", "get")


def test_defaults_and_nullable_overrides(api):
    client, stub, _ = api
    stub.result = NestedOutput(data={})
    for body in [
        {"agent_type": "dummy"},
        {
            "agent_type": "dummy",
            "execution_id": None,
            "config": {
                "timeout_seconds": None,
                "api_key": None,
                "model": {
                    "provider": None,
                    "name": None,
                    "temperature": None,
                    "max_tokens": None,
                },
            },
        },
    ]:
        assert client.post("/api/agents/run", json=body).status_code == 200
        assert stub.received == (
            "dummy",
            {
                "model": {
                    "provider": None,
                    "name": None,
                    "temperature": None,
                    "max_tokens": None,
                },
                "timeout_seconds": None,
                "api_key": None,
            },
            {},
            None,
        )


def test_documented_response_examples_validate(api):
    client, _, _ = api
    spec = client.get("/openapi.json").json()
    for item in spec["paths"].values():
        for operation in item.values():
            for response in operation["responses"].values():
                media = response.get("content", {}).get("application/json", {})
                if "schema" not in media:
                    continue
                validator = Draft202012Validator(
                    {"components": spec["components"], **media["schema"]}
                )
                if "example" in media:
                    validator.validate(media["example"])
                for example in media.get("examples", {}).values():
                    validator.validate(example["value"])


def test_service_resolves_defaults_and_zero_overrides(api, monkeypatch):
    _, _, service = api
    captured = {}

    class StubAgent:
        def __init__(self, settings, model):
            self.settings = settings

    def build_model(settings, credentials):
        captured["settings"] = settings.model_dump()
        captured["key"] = credentials.api_key
        return object()

    monkeypatch.setattr(service._registry, "get", lambda name: StubAgent)
    monkeypatch.setattr(execution_service, "build_model", build_model)
    monkeypatch.setattr(service, "_server_api_key", lambda: "configured-key")
    service._base_config = {}
    agent, timeout = service.build_agent(
        "example", ExecutionConfig(model=ModelConfig(name="example-model"))
    )
    assert timeout == agent.settings.timeout_seconds == 60
    assert captured == {
        "settings": {
            "provider": "gemini",
            "name": "example-model",
            "temperature": 0.2,
            "max_tokens": 40000,
        },
        "key": "configured-key",
    }
    _, timeout = service.build_agent(
        "example",
        ExecutionConfig(
            model=ModelConfig(
                provider="", name="example-model", temperature=0, max_tokens=0
            ),
            api_key="",
            timeout_seconds=5,
        ),
    )
    assert timeout == 5
    assert (
        captured["settings"]["temperature"] == captured["settings"]["max_tokens"] == 0
    )
    assert captured["key"] == "configured-key"
    with pytest.raises(InvalidConfigError, match="model.name is required"):
        service.build_agent("example", ExecutionConfig())
    with pytest.raises(InvalidConfigError, match="timeout_seconds must be positive"):
        service.build_agent(
            "example",
            ExecutionConfig(
                model=ModelConfig(name="example-model"),
                timeout_seconds=0,
            ),
        )


def test_service_rejects_invalid_agent_input_before_execution(api, monkeypatch):
    _, _, service = api

    class StubAgent:
        input_schema = DummyInput

        async def run(self, payload):
            pytest.fail("Invalid input must not reach the agent")

    monkeypatch.setattr(service, "build_agent", lambda *args: (StubAgent(), 60))
    with pytest.raises(InvalidInputError, match="Invalid input for agent 'dummy'"):
        asyncio.run(service.run("dummy", ExecutionConfig(), {}))
