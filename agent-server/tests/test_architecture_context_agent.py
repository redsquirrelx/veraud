"""Production direct execution uses the real documentary graph, offline."""

import json
import subprocess
from types import SimpleNamespace
from typing import get_args
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.agents.architecture_context.schemas import RetrievalCategory
from server.api.executions import router
from server.app.execution_service import AgentExecutionService, get_execution_service


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args]).decode().strip()


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "repository"
    root.mkdir()
    git(root, "init")
    (root / "README.md").write_text("# Architecture\nGateway routes requests.\n", encoding="utf-8")
    git(root, "add", ".")
    git(root, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "docs")
    commit = git(root, "rev-parse", "HEAD")
    (root / "README.md").write_text("Uncommitted and unrelated content", encoding="utf-8")
    return root, commit


@pytest.fixture
def host(monkeypatch, tmp_path):
    async def respond(messages, **kwargs):
        prompt = messages[0].content
        if "Retrieval context:\n" in prompt:
            context = json.loads(prompt.split("Retrieval context:\n", 1)[1])
            payload = {"tasks": [] if context["executed_tasks"] else [{
                "category": "components", "operation": "read", "path": "README.md",
            }]}
        elif "Retrieved sections:\n" in prompt:
            section = json.loads(prompt.split("Retrieved sections:\n", 1)[1])[0]
            payload = {"sections": [{"section_id": section["section_id"], "issues": [], "claims": [{
                "category": "components", "subject": "Gateway", "statement": "Routes requests",
                "certainty": "explicit", "reasoning": "Documented", "section_ids": [section["section_id"]],
                "evidence": [{"section_id": section["section_id"], "start_line": 2, "end_line": 2}],
            }]}]}
        else:
            payload = {"categories": [{"category": category, "sufficient": category == "components",
                                       "rationale": "Documentary fixture"}
                                      for category in get_args(RetrievalCategory)]}
        return SimpleNamespace(content=json.dumps(payload), usage_metadata={"input_tokens": 100, "output_tokens": 20})

    chat = SimpleNamespace(ainvoke=AsyncMock(side_effect=respond))
    model = SimpleNamespace(llm=chat, settings=SimpleNamespace(name="offline", max_tokens=4000))
    callbacks = SimpleNamespace(mark_running=AsyncMock(), progress=AsyncMock(), complete=AsyncMock(), aclose=AsyncMock())
    monkeypatch.setattr("server.config.tracing.setup", lambda: None)
    monkeypatch.setattr("server.agents.architecture_context.agent.default_database", lambda: tmp_path / "index.sqlite")
    monkeypatch.setattr("server.app.execution_service.build_model", lambda *args: model)
    # The host owns provider cleanup; the offline client has no connections.
    monkeypatch.setattr("server.app.execution_service.close_model_client", AsyncMock())
    service = AgentExecutionService(callbacks_factory=lambda: callbacks)
    app = FastAPI()
    app.state.blackboard = None
    app.include_router(router)
    app.dependency_overrides[get_execution_service] = lambda: service
    with TestClient(app) as client:
        yield client, chat, callbacks


def test_direct_endpoint_runs_selected_commit_and_reports_partial_output_and_usage(repository, host):
    root, commit = repository
    client, chat, callbacks = host
    assert "architecture_context" in client.get("/api/agents").json()
    schema = client.get("/api/agents/architecture_context/schema").json()
    assert "root_path" in schema["input_schema"]["required"]
    response = client.post("/api/agents/run", json={
        "agent_type": "architecture_context", "execution_id": 42,
        "config": {"model": {"name": "offline"}, "timeout_seconds": 30},
        "input": {"root_path": str(root), "commit_hash": commit},
    })
    assert response.status_code == 200, response.text
    output = response.json()["result"]
    assert output["document_index"]["commit"] == commit
    assert output["execution_status"] == "partial", output["execution_error"]
    assert output["knowledge"][0]["evidence"][0]["quote"] == "Gateway routes requests.\n"
    assert output["pending_categories"]
    assert output["validation_errors"] == []
    assert "Uncommitted" not in json.dumps(output)
    assert chat.ainvoke.await_count == 4
    outcome = callbacks.complete.call_args.args[1]
    assert json.loads(outcome.result) == output
    assert outcome.input_tokens == 400
    assert outcome.output_tokens == 80
    assert callbacks.progress.await_count == 4


def test_direct_input_rejects_narrative_overrides_and_invalid_commit(repository, host):
    root, _ = repository
    client, _, _ = host
    base = {"agent_type": "architecture_context", "config": {"model": {"name": "offline"}}}
    response = client.post("/api/agents/run", json={**base, "input": {"root_path": str(root), "prompt": "override"}})
    assert response.status_code == 422
    response = client.post("/api/agents/run", json={**base, "input": {"root_path": str(root), "commit_hash": "missing-commit"}})
    assert response.status_code != 200


def test_complete_documentary_coverage_remains_native(repository, host):
    root, commit = repository
    client, chat, _ = host
    original = chat.ainvoke.side_effect

    async def complete(messages, **kwargs):
        response = await original(messages, **kwargs)
        payload = json.loads(response.content)
        if "sections" in payload:
            claim = payload["sections"][0]["claims"][0]
            payload["sections"][0]["claims"] = [
                {**claim, "category": category} for category in get_args(RetrievalCategory)
            ]
        elif "categories" in payload:
            for assessment in payload["categories"]:
                assessment["sufficient"] = True
        response.content = json.dumps(payload)
        return response

    chat.ainvoke.side_effect = complete
    response = client.post("/api/agents/run", json={
        "agent_type": "architecture_context", "config": {"model": {"name": "offline"}},
        "input": {"root_path": str(root), "commit_hash": commit},
    })
    assert response.status_code == 200, response.text
    output = response.json()["result"]
    assert output["execution_status"] == "complete"
    assert len(output["knowledge"]) == 7
    assert output["pending_categories"] == []
    assert chat.ainvoke.await_count == 3


def test_empty_documentation_is_partial_without_model_calls(repository, host):
    root, _ = repository
    git(root, "rm", "-f", "README.md")
    git(root, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "no docs")
    commit = git(root, "rev-parse", "HEAD")
    client, chat, _ = host
    response = client.post("/api/agents/run", json={
        "agent_type": "architecture_context", "config": {"model": {"name": "offline"}},
        "input": {"root_path": str(root), "commit_hash": commit},
    })
    assert response.status_code == 200, response.text
    output = response.json()["result"]
    assert output["execution_status"] == "partial"
    assert output["knowledge"] == []
    assert len(output["pending_categories"]) == 7
    chat.ainvoke.assert_not_awaited()
