import pytest
from fastapi.testclient import TestClient

from server.app.audit_configuration import resolve_attribute_limits
from server.main import app


@pytest.mark.parametrize("attribute,exclusive", [("maintainability", "call_limits"),
    ("security", "security_config"), ("functional_adequacy", "functional_config")])
def test_drawer_schema_and_validation_use_runtime_contracts(attribute, exclusive):
    with TestClient(app) as client:
        descriptor = client.get(f"/api/audits/configuration/{attribute}").json()
        assert descriptor["level"] == "developer"
        schema = descriptor["schema"]
        assert set(schema["properties"]) == {"agent_defaults", "audit_budget", exclusive}
        defaults = {"max_context_characters": 20000000, "max_total_tokens": 80000000,
            "max_model_calls": 20, "max_tool_calls": 200}
        options = {"agent_defaults": defaults, "audit_budget": {"max_total_tokens": 300000000000}}
        if attribute == "maintainability":
            options[exclusive] = {"manager": {"max_tool_calls": 400}, "coordinator": {"max_tool_calls": 180},
                "investigator": {"max_tool_calls": 60}}
        elif attribute == "security":
            options[exclusive] = {"max_retrieved_characters": 20000000, "max_scan_files": 500, "max_tool_calls": 2000}
        else:
            options[exclusive] = {"embedding_model": "all-MiniLM-L6-v2", "retrieval_top_k": 3}
        response = client.post(f"/api/audits/configuration/{attribute}/validate", json=options)
        assert response.status_code == 200, response.text
        assert response.json()["values"] == options
        resolved = resolve_attribute_limits(attribute, options)
        assert resolved.max_context_characters == 20000000
        assert resolved.max_total_tokens == 80000000
        if attribute == "maintainability":
            assert resolved.max_tool_calls == 400
            assert resolved.invocation_limits.max_tool_calls == 180
            assert resolved.invocation_limits.invocation_limits.max_tool_calls == 60
        elif attribute == "security":
            assert resolved.max_scan_files == 500 and resolved.max_tool_calls == 2000
        else:
            assert resolved.retrieval_top_k == 3
        assert client.post(f"/api/audits/configuration/{attribute}/validate", json={"agent_defaults": {
            "max_context_characters": 1}}).status_code == 422
        assert client.post(f"/api/audits/configuration/{attribute}/validate", json={"agent_defaults": {
            "max_candidates": 4}}).status_code == 422


def test_category_settings_cannot_expose_another_category_or_credentials():
    with TestClient(app) as client:
        assert client.get("/api/audits/configuration/unknown").status_code == 422
        for values in ({"security_config": {}}, {"api_key": "not-a-setting"}):
            assert client.post("/api/audits/configuration/maintainability/validate", json=values).status_code == 422
