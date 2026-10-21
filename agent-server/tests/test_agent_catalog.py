"""Backend discovery must reflect runnable contracts without executing agents."""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from config.agents.catalog import describe_agent_config, list_agent_configs
from server.agents.dummy.agent import DummyAgent
from server.agents.maintainability.manager.registry import COORDINATORS
from server.agents.maintainability.modularity.coordinator.registry import (
    INVESTIGATORS as MODULARITY,
)
from server.agents.maintainability.reusability.coordinator.registry import (
    INVESTIGATORS as REUSABILITY,
)
from server.api.executions import router
from server.api.schemas import ExecutionConfig, ModelConfig
from server.app.agent_registry import AgentRegistry
from server.app.audit_models import validate_model_configs
from server.app.execution_service import AgentExecutionService, get_execution_service


@pytest.fixture
def client(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Discovery must not create models or security supervisors")

    monkeypatch.setattr("server.config.tracing.setup", lambda: None)
    monkeypatch.setattr("server.app.execution_service.build_model", unexpected)
    monkeypatch.setattr("server.agents.security.security_manager.agent.SecuritySupervisorAgent.__init__", unexpected)
    service = AgentExecutionService()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_execution_service] = lambda: service
    with TestClient(app) as value:
        yield value


def test_catalog_covers_existing_configuration_and_real_hierarchy_without_changing_direct_execution(client):
    response = client.get("/api/agents/catalog")
    assert response.status_code == 200
    catalog = response.json()
    assert catalog["schema_version"] == "1.0"
    agents = {item["agent_id"]: item for item in catalog["agents"]}
    assert list(agents) == sorted(agents)
    assert {item["configuration_id"] for item in agents.values() if item["configuration_id"]} == set(list_agent_configs())
    assert agents["maintainability_manager"]["child_ids"] == list(COORDINATORS)
    for coordinator, investigators in (("modularity", MODULARITY), ("reusability", REUSABILITY)):
        assert agents[coordinator]["child_ids"] == list(investigators)
        for identifier in investigators:
            assert agents[identifier]["parent_ids"] == [coordinator]
            assert agents[identifier]["execution_modes"] == ["internal"]
    for identifier, agent in agents.items():
        assert set(agent["parent_ids"] + agent["child_ids"]) <= agents.keys()
        for child in agent["child_ids"]:
            assert identifier in agents[child]["parent_ids"]
    assert not agents["audit_report"]["requires_model"]
    assert agents["audit_report"]["model_configuration_id"] is None
    assert agents["remediation_synthesizer"]["model_configuration_id"] == "security"
    assert agents["dast_sandbox"]["availability"] == "not_executed"
    direct = client.get("/api/agents").json()
    assert direct == sorted(key for key, value in agents.items() if "direct" in value["execution_modes"])
    assert client.get("/api/agents/modularity/schema").status_code == 404


def test_backend_can_resolve_all_attribute_selections_into_valid_model_maps_and_callback_keys(client):
    workflows = {item["workflow_id"]: item for item in client.get("/api/agents/catalog").json()["workflows"]}
    quality = workflows["quality-audit"]
    assert quality["supported_attributes"] == ["maintainability", "security", "functional_adequacy"]
    assert len(quality["attribute_selections"]) == 7
    assert quality["input_schema"]["properties"]["attributes"]
    for selection in quality["attribute_selections"]:
        configs = {identifier: ExecutionConfig(model=ModelConfig(provider="gemini", name="example"), api_key="test-key")
            for identifier in selection["model_configuration_ids"]}
        validate_model_configs(configs, selection["attributes"])
        expected = "maintainability_manager" if "maintainability" in selection["attributes"] else (
            "security" if "security" in selection["attributes"] else "functional_adequacy")
        assert selection["stages"] == [expected]
    project = workflows["project-architecture"]
    assert project["stages"] == list(project["model_configuration_groups"])
    assert project["run_url"] == "/api/pipelines/project-architecture/run"


def test_quality_contexts_are_explicit_for_hierarchies_shared_reports_and_non_audit_workflows(client):
    catalog = client.get("/api/agents/catalog").json()
    agents = {item["agent_id"]: item for item in catalog["agents"]}
    quality = next(item for item in catalog["workflows"] if item["workflow_id"] == "quality-audit")
    for attribute, participants in quality["model_configuration_groups"].items():
        for identifier in participants:
            assert agents[identifier]["quality_attributes"] == [attribute]
    for identifier in agents["security"]["child_ids"]:
        assert agents[identifier]["quality_attributes"] == ["security"]
    assert agents["audit_report"]["quality_attributes"] == ["maintainability", "security", "functional_adequacy"]
    assert agents["functional_adequacy"]["quality_attributes"] == ["functional_adequacy"]
    for identifier in ("orientation", "architecture", "semantic_validation"):
        assert agents[identifier]["quality_attributes"] == []
        assert agents[identifier]["workflow_ids"] == ["project-architecture"]
    assert agents["dummy"]["quality_attributes"] == []
    detail = client.get("/api/agents/catalog/audit_report").json()
    assert detail["quality_attributes"] == agents["audit_report"]["quality_attributes"]


def test_all_details_resolve_public_settings_and_contracts_without_credentials_or_internal_config(client):
    agents = client.get("/api/agents/catalog").json()["agents"]
    for agent in agents:
        response = client.get(agent["detail_url"])
        assert response.status_code == 200, agent["agent_id"]
        detail = response.json()
        assert detail["agent_id"] == agent["agent_id"]
        if agent["configuration_id"]:
            assert detail["configuration"] == describe_agent_config(agent["configuration_id"])
            assert detail["configuration"]["level"] == "user"
            fields = detail["configuration"]["config_schema"]["properties"]
            assert not {"max_tool_calls", "max_model_calls", "tools", "prompts", "api_key"} & fields.keys()
        else:
            assert detail["configuration"] is None
        assert '"api_key"' not in json.dumps(detail)
    detail = client.get("/api/agents/catalog/architecture_boundary").json()
    assert detail["input_schema"] == MODULARITY["architecture_boundary"].request_class.model_json_schema()
    assert detail["output_schema"] == MODULARITY["architecture_boundary"].result_class.model_json_schema()
    assert client.get("/api/agents/catalog/project_orientation").json()["agent_id"] == "orientation"
    assert client.get("/api/agents/catalog/absent").status_code == 404
    assert client.get("/api/agents/catalog/dast_sandbox").json()["input_schema"] is None


def test_new_direct_registration_is_discovered_from_the_injected_registry(monkeypatch):
    monkeypatch.setattr("server.config.tracing.setup", lambda: None)
    registry = AgentRegistry()
    registry.register("custom", DummyAgent)
    service = AgentExecutionService(registry=registry)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_execution_service] = lambda: service
    with TestClient(app) as client:
        catalog = client.get("/api/agents/catalog").json()
        assert "custom" in {agent["agent_id"] for agent in catalog["agents"]}
        assert "dummy" not in {agent["agent_id"] for agent in catalog["agents"]}
        detail = client.get("/api/agents/catalog/custom").json()
        assert detail["input_schema"] == DummyAgent.input_schema.model_json_schema()
        assert detail["output_schema"] == DummyAgent.output_schema.model_json_schema()
        openapi = client.get("/openapi.json").json()
        assert openapi["paths"]["/api/agents/catalog"]["get"]["responses"]["200"]
