import asyncio
import importlib.util
import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from langgraph.graph import END, START
from pydantic import ValidationError

from config.agents import InvestigationConfig
from config.agents.catalog import describe_agent_config, validate_developer_agent_config
from server.agents.maintainability.modularity.architecture_boundary import (
    ArchitectureBoundaryAgent,
    AuditRequest,
    AuditResult,
    BoundaryConfig,
)
from server.agents.maintainability.modularity.architecture_boundary.planning import (
    balance_candidates,
    candidate_rank,
)
from server.runtimes.repository.context import RepositoryContext
from server.runtimes.repository.schemas import ExecutionBudget, RepositoryInput
from server.runtimes.repository.tools import RepositoryToolset, ToolLimits
from server.services.repository_analysis import RepositoryAnalysisService


class PlanningModel:
    def __init__(self, response=None):
        self.response = response
        self.contexts = []

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages, **kwargs):
        context = json.loads(messages[1].content)
        self.contexts.append(context)
        result = self.response(context) if self.response else {
            "opportunity_ids": [task["id"] for task in context["opportunities"][:context["budget"]["max_investigations"]]]}
        return AIMessage(content=json.dumps(result), usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120})


def tools_for(tmp_path, contents, *, limits=None, transform=None):
    root = tmp_path / "repo"
    root.mkdir()
    for path, content in contents.items():
        file = root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content, encoding="utf-8")
    snapshot = RepositoryAnalysisService().analyze_sync(root)
    if transform:
        snapshot = transform(snapshot)
    return RepositoryToolset(RepositoryContext(snapshot, RepositoryInput(
        snapshot_hash=snapshot.repository.snapshot_hash, budget=ExecutionBudget(max_input_tokens_per_call=50_000),
    )), workspace_root=tmp_path, limits=limits)


def run_plan(tools, model=None, request=None, **overrides):
    model = model or PlanningModel()
    config = BoundaryConfig(**({"max_output_tokens": 1000, "provider_request_interval_seconds": 0,
        "max_context_characters": 60_000} | overrides))
    agent = ArchitectureBoundaryAgent(model, config)
    execution = agent.execution_type(model, config, tools, request or AuditRequest())
    async def plan_only():
        with execution.timing.stage("investigation"):
            return (await execution.plan_investigation(execution.initial_state()))["result"]
    return asyncio.run(plan_only()), model


def cycles(project="", count=1):
    result = {}
    for i in range(count):
        prefix = f"{project}/" if project else ""
        result[prefix + f"parts{i}/a.py"] = "from .b import f\ndef f(): pass\n"
        result[prefix + f"parts{i}/b.py"] = "from .a import f\ndef f(): pass\n"
    return result


def assert_grounded(result, tools):
    snapshot = tools.accessible_snapshot
    paths = {file.path: file for file in snapshot.files}
    relations = {item.id: item for item in snapshot.relationships}
    assert len({task.id for task in result.plan.investigations}) == len(result.plan.investigations) <= 15
    assert not result.plan.hypotheses and not result.hypotheses and not result.findings
    assert AuditResult.model_validate_json(result.model_dump_json()) == result
    for task in result.plan.investigations:
        assert set(task.scope) <= paths.keys()
        assert task.question and task.evidence_needed and task.completion_condition and task.investigation_strategy
        assert task.structural_signal.observed and task.structural_signal.inference
        assert set(task.structural_signal.symbol_ids) <= {symbol.id for symbol in snapshot.symbols}
        for reference in task.structural_signal.relationships:
            actual = relations[reference.id]
            assert (reference.source_id, reference.target_id, reference.kind) == (actual.source_id, actual.target_id, actual.kind)
        for link in task.structural_signal.integration_links:
            for point in [link.client, *link.endpoints, *link.binding_points]:
                file = paths[point.path]
                assert (point.file_id, point.content_hash) == (file.id, file.content_hash)
                assert 1 <= point.start_line <= point.end_line <= file.line_count
                if point.indexed_entrypoint_id:
                    assert point.indexed_entrypoint_id in {entry.id for entry in snapshot.entrypoints}
    assert result.investigation_tasks == [task.model_dump() for task in result.plan.investigations]


@pytest.fixture
def applications():
    contents = {"frontend/package.json": '{"name":"ui"}', "backend/package.json": '{"name":"api"}',
        "agent-server/pyproject.toml": '[project]\nname="agents"\nversion="0.0.0"\n'}
    for project in ("frontend", "backend", "agent-server"):
        contents.update(cycles(project, 4))
    contents.update({
        "frontend/client.ts": "export async function load() { return fetch('http://localhost:4100/api/orders'); }\n",
        "backend/server.ts": "import express from 'express';\nconst app = express();\napp.get('/api/orders', (req,res) => res.json([]));\napp.listen(4100);\n",
        "backend/agent_client.py": "import httpx\nasync def execute():\n    return await httpx.post('http://localhost:8100/run')\n",
        "agent-server/api.py": "from fastapi import FastAPI\nimport uvicorn\napp = FastAPI()\n@app.post('/run')\ndef run(): return {}\nuvicorn.run(app, host='127.0.0.1', port=8100)\n",
        "backend/ai-providers.integration.test.ts": "fetch('http://localhost:9999/test-only');\n",
        "frontend/fixtures/fake.ts": "fetch('http://localhost:9999/fixture-only');\n",
    })
    return contents


def test_three_internal_applications_and_both_code_backed_integrations(tmp_path, applications):
    tools = tools_for(tmp_path, applications)
    result, model = run_plan(tools)
    assert result.termination_reason == "planning_completed"
    assert len(result.plan.investigations) == 12
    assert {project for task in result.plan.investigations if task.scope_kind == "internal" for project in task.project_ids} == {
        project.id for project in tools.accessible_snapshot.projects if project.path in {"frontend", "backend", "agent-server"}}
    links = [link for task in result.plan.investigations for link in task.structural_signal.integration_links]
    roots = {project.id: project.path for project in tools.accessible_snapshot.projects}
    assert {(roots[link.client.project_id], roots[link.target_project_id]) for link in links if link.target_project_id} == {
        ("frontend", "backend"), ("backend", "agent-server")}
    assert all(link.match_basis == "authority_route_method" and link.status == "structural_candidate" for link in links)
    assert all(".test." not in path and "/fixtures/" not in path for task in result.plan.investigations for path in task.scope)
    assert result.model_calls == 1 and result.tool_calls == 0
    assert result.accounted_tokens == 120 and result.estimated_tokens == 0
    assert len(json.dumps(model.contexts[0])) < 20_000
    assert result.investigation_coverage["integrations"]["matched_clients"] == 2
    assert_grounded(result, tools)


@pytest.fixture
def acyclic_apps_with_inferred_apis():
    contents = {"frontend/package.json": '{"name":"ui"}', "backend/package.json": '{"name":"api"}',
        "agent-server/pyproject.toml": '[project]\nname="agents"\nversion="0.0.0"\n'}
    # No cycles, reversed directions, network calls or indexed public_api in
    # either JS application: these must survive as component-boundary probes.
    for project in ("frontend", "backend"):
        for i in range(3):
            contents[f"{project}/src/component{i}/caller.ts"] = (
                f"import {{f}} from '../contract{i}/impl';\nexport function use() {{ return f(); }}\n")
            contents[f"{project}/src/contract{i}/impl.ts"] = "export function f() { return 1; }\n"
        contents[f"{project}/src/component0/caller.spec.ts"] = "import {f} from '../contract0/impl';\n"
    # Many weaker API labels must not crowd out the grounded JS menu entries.
    for i in range(12):
        contents[f"agent-server/lib{i}/__init__.py"] = "from .impl import f\n"
        contents[f"agent-server/lib{i}/impl.py"] = "def f(): pass\n"
        contents[f"agent-server/use{i}a/caller.py"] = f"import lib{i}\n"
        contents[f"agent-server/use{i}b/caller.py"] = f"import lib{i}\n"
        contents[f"agent-server/use{i}c/caller.py"] = f"from lib{i}.impl import f\n"
    return contents


def test_model_bias_is_reported_without_adding_unselected_applications(tmp_path, acyclic_apps_with_inferred_apis):
    tools = tools_for(tmp_path, acyclic_apps_with_inferred_apis, limits=ToolLimits(max_metadata_items=8))
    model = PlanningModel(lambda context: {"opportunity_ids": [task["id"] for task in context["opportunities"]
        if task["scope"][0].startswith("agent-server/")]})
    result, model = run_plan(tools, model, max_planned_investigations=6)
    rows = {row["root"]: row for row in result.investigation_coverage["by_project"]}
    assert set(rows) == {"frontend", "backend", "agent-server"}
    assert all(row["internal_menu_candidates"] > 0 for row in rows.values())
    assert rows["frontend"]["model_selected"] == rows["backend"]["model_selected"] == 0
    assert rows["frontend"]["internal_selected"] == rows["backend"]["internal_selected"] == 0
    assert rows["frontend"]["internal_candidates_generated"] == rows["backend"]["internal_candidates_generated"] == 3
    assert result.investigation_coverage["selection_bias_detected"]
    chosen = {task["id"] for task in model.contexts[0]["opportunities"] if task["scope"][0].startswith("agent-server/")}
    assert {task.id for task in result.plan.investigations} == chosen
    assert 0 < len(chosen) < 6
    assert not result.investigation_coverage["selection_rebalanced"]
    assert result.investigation_coverage["selection_added_ids"] == []
    for task in result.plan.investigations:
        assert all(".spec." not in path for path in task.scope)
        assert all(path.startswith("agent-server/") for path in task.scope)
    assert result.model_calls == 1 and result.tool_calls == 0
    assert_grounded(result, tools)


@pytest.mark.parametrize("count", [0, 1, 3])
def test_model_can_abstain_or_select_fewer_than_twelve_tasks(tmp_path, count):
    tools = tools_for(tmp_path, cycles(count=5))
    model = PlanningModel(lambda context: {"opportunity_ids": [task["id"] for task in context["opportunities"][:count]]})
    result, _ = run_plan(tools, model)
    chosen = {task["id"] for task in model.contexts[0]["opportunities"][:count]}
    assert len(result.plan.investigations) == count
    assert {task.id for task in result.plan.investigations} == chosen
    assert result.model_calls == 1 and result.tool_calls == 0
    assert result.investigation_coverage["selection_added_ids"] == []


def test_balancing_preserves_diversity_only_within_selected_projects(tmp_path):
    result, _ = run_plan(tools_for(tmp_path, cycles(count=5)))
    menu = result.plan.investigations
    projects = {task.id: [project] for task, project in zip(menu, ["a", "a", "b", "c", "unselected"], strict=True)}
    selected = balance_candidates(menu, projects, 12, preferred=menu[:4])
    assert {task.id for task in selected} == {task.id for task in menu[:4]}
    assert {projects[task.id][0] for task in selected[:3]} == {"a", "b", "c"}
    assert balance_candidates(menu, projects, 12, preferred=[]) == []


def test_small_menu_and_context_preserve_real_internal_application_diversity(tmp_path, acyclic_apps_with_inferred_apis):
    tools = tools_for(tmp_path, acyclic_apps_with_inferred_apis, limits=ToolLimits(max_metadata_items=3))
    result, model = run_plan(tools, max_planned_investigations=3, max_context_characters=14_000)
    assert result.termination_reason == "planning_completed"
    assert len(result.plan.investigations) == len(model.contexts[0]["opportunities"]) == 3
    assert all(row["internal_selected"] == 1 for row in result.investigation_coverage["by_project"])
    assert result.model_calls == 1 and result.tool_calls == 0
    assert_grounded(result, tools)


def test_dependencies_without_boundary_support_do_not_force_application_quotas(tmp_path, acyclic_apps_with_inferred_apis):
    contents = {path: text for path, text in acyclic_apps_with_inferred_apis.items() if not path.startswith("frontend/src/")}
    contents["frontend/run.ts"] = "import {value} from './helper';\n"
    contents["frontend/helper.ts"] = "export const value = 1;\n"
    tools = tools_for(tmp_path, contents)
    result, _ = run_plan(tools, max_planned_investigations=6)
    row = next(row for row in result.investigation_coverage["by_project"] if row["root"] == "frontend")
    assert row["eligible_relationships"] > 0 and row["component_seeds_without_boundary_support"] > 0
    assert row["internal_candidates_generated"] == row["internal_selected"] == 0
    assert not any(path.startswith("frontend/") for task in result.plan.investigations for path in task.scope)
    assert_grounded(result, tools)


def test_repeated_component_interactions_keep_their_independent_references(tmp_path):
    tools = tools_for(tmp_path, {
        "src/ui/one.ts": "import {value} from '../contract/one'; export const one = value;\n",
        "src/ui/two.ts": "import {value} from '../contract/two'; export const two = value;\n",
        "src/contract/one.ts": "export const value = 1;\n", "src/contract/two.ts": "export const value = 2;\n",
    })
    result, _ = run_plan(tools)
    assert len(result.plan.investigations) == 1
    task = result.plan.investigations[0]
    assert task.structural_signal.kind == "component_boundary"
    assert len(task.structural_signal.relationships) == 2
    assert "declarations at both endpoints=False" in task.structural_signal.observed[0]
    assert "distinct module-pair interactions=2" in task.structural_signal.observed[0]
    assert_grounded(result, tools)


def test_weak_api_label_does_not_suppress_better_indexed_boundary_evidence(tmp_path):
    tools = tools_for(tmp_path, {"component/__init__.py": "from .impl import f\n",
        "component/impl.py": "def f(): pass\n", "first/use.py": "import component\n",
        "second/use.py": "import component\n",
        "third/use.py": "from component.impl import f\ndef use(): return f()\n"})
    result, _ = run_plan(tools)
    assert len(result.plan.investigations) == 1
    task = result.plan.investigations[0]
    assert task.structural_signal.kind == "component_boundary" and task.structural_signal.basis == "indexed"
    assert len(task.structural_signal.symbol_ids) == 2
    assert result.investigation_coverage["opportunities"]["generated_by_type"]["encapsulation"] == 1
    assert result.investigation_coverage["opportunities"]["deduplicated"] >= 1
    assert_grounded(result, tools)


@pytest.mark.parametrize("maximum", [6, 10, 15])
def test_configurable_plan_size_and_compact_context(tmp_path, maximum):
    tools = tools_for(tmp_path, cycles(count=18))
    result, model = run_plan(tools, max_planned_investigations=maximum)
    assert len(result.plan.investigations) == maximum
    assert len(model.contexts[0]["opportunities"]) <= tools.limits.max_metadata_items
    assert all("integration_links" not in task and "evidence_needed" not in task and "question" not in task for task in model.contexts[0]["opportunities"])
    assert len(json.dumps(model.contexts[0])) < 20_000
    assert_grounded(result, tools)


def test_no_padding_for_ordinary_imports_or_empty_applications(tmp_path):
    tools = tools_for(tmp_path, {"run.py": "import helper\n", "helper.py": "def f(): pass\n",
        "README.md": "Mandatory Clean Architecture: helper is forbidden", "unused/package.json": '{"name":"unused"}'})
    result, model = run_plan(tools)
    assert not result.plan.investigations and not model.contexts
    assert result.investigation_coverage["opportunities"]["quality_discarded_relationship_seeds"] > 0
    assert_grounded(result, tools)


@pytest.mark.parametrize("url", ["http://foreign.invalid/api/orders", "/api/orders", "DYNAMIC_URL"])
def test_unknown_destinations_do_not_invent_inter_application_edges(tmp_path, applications, url):
    contents = {path: text for path, text in applications.items() if "client" not in path}
    contents["frontend/client.ts"] = f"fetch({json.dumps(url) if url != 'DYNAMIC_URL' else url});\n"
    tools = tools_for(tmp_path, contents)
    result, _ = run_plan(tools, request=AuditRequest(targets=["frontend/client.ts"]))
    links = [link for task in result.plan.investigations for link in task.structural_signal.integration_links]
    assert links and all(link.target_project_id is None and link.status == "ambiguous" for link in links)
    assert not any(task.scope_kind == "inter_application" for task in result.plan.investigations)
    if url.startswith("http://foreign"):
        assert all(not link.endpoints for link in links)
    assert_grounded(result, tools)


def test_unconnected_applications_are_not_connected_by_common_imports(tmp_path):
    contents = {"one/package.json": '{"name":"one"}', "two/package.json": '{"name":"two"}'}
    contents.update(cycles("one"))
    contents.update(cycles("two"))
    tools = tools_for(tmp_path, contents)
    result, _ = run_plan(tools)
    assert len(result.plan.investigations) == 2
    assert all(task.scope_kind == "internal" for task in result.plan.investigations)
    assert_grounded(result, tools)


def test_literal_client_factories_resolve_bases_with_binding_provenance(tmp_path, applications):
    applications["frontend/client.ts"] = (
        "import axios from 'axios';\nconst BASE = 'http://localhost:4100';\n"
        "const api = axios.create({baseURL: BASE});\napi.get('/api/orders');\n")
    applications["backend/agent_client.py"] = (
        "import httpx\nasync def execute():\n"
        "    async with httpx.AsyncClient(base_url='http://localhost:8100') as client:\n"
        "        return await client.post('/run')\n")
    tools = tools_for(tmp_path, applications)
    result, _ = run_plan(tools)
    links = [link for task in result.plan.investigations for link in task.structural_signal.integration_links]
    assert len(links) == 2 and all(link.target_project_id and link.binding_points for link in links)
    assert_grounded(result, tools)


def test_comments_strings_and_shadowed_network_names_do_not_create_clients(tmp_path):
    tools = tools_for(tmp_path, {
        "one.ts": "// fetch('http://localhost:4100/api/orders');\n"
            "const note = \"fetch('http://localhost:4100/api/orders')\";\n"
            "function fetch(url: string) { return url; }\nfetch('http://localhost:4100/api/orders');\n",
        "two.ts": "export function use(fetch: any) { return fetch('http://localhost:4100/api/orders'); }\n",
        "three.py": "import requests\ndef use(requests):\n    return requests.get('http://localhost:4100/api/orders')\n",
    })
    result, model = run_plan(tools)
    assert not result.plan.investigations and not model.contexts
    assert result.investigation_coverage["integrations"]["generated_opportunities"] == 0


def test_conflicting_listener_bindings_remain_ambiguous(tmp_path, applications):
    applications["agent-server/api.py"] = (
        "from fastapi import FastAPI\nimport uvicorn\napp = FastAPI()\n"
        "@app.get('/api/orders')\ndef orders(): return []\nuvicorn.run(app, port=4100)\n")
    applications.pop("backend/agent_client.py")
    tools = tools_for(tmp_path, applications)
    result, _ = run_plan(tools, request=AuditRequest(targets=["frontend/client.ts"]))
    link = result.plan.investigations[0].structural_signal.integration_links[0]
    assert link.target_project_id is None and link.match_basis == "ambiguous_destination"
    assert len({point.project_id for point in link.endpoints}) == 2
    assert_grounded(result, tools)


def test_dynamic_http_method_is_not_invented_as_get(tmp_path, applications):
    applications["frontend/client.ts"] = "fetch('http://localhost:4100/api/orders', {method: METHOD});\n"
    tools = tools_for(tmp_path, applications)
    result, _ = run_plan(tools, request=AuditRequest(targets=["frontend/client.ts"]))
    link = result.plan.investigations[0].structural_signal.integration_links[0]
    assert link.client.method is None and link.target_project_id is None
    assert_grounded(result, tools)


def test_multiple_entrypoints_for_one_integration_boundary_are_one_investigation(tmp_path, applications):
    applications["frontend/more.ts"] = "fetch('http://localhost:4100/api/users');\n"
    applications["backend/server.ts"] += "app.get('/api/users', (req,res) => res.json([]));\n"
    tools = tools_for(tmp_path, applications)
    result, _ = run_plan(tools)
    tasks = [task for task in result.plan.investigations if any(link.client.path.startswith("frontend/") for link in task.structural_signal.integration_links)]
    assert len(tasks) == 1 and len(tasks[0].structural_signal.integration_links) == 2
    assert_grounded(result, tools)


def test_distinct_boundaries_sharing_an_application_are_not_deduplicated(tmp_path, applications):
    applications["frontend/auth.ts"] = "fetch('http://localhost:4100/auth/session');\n"
    applications["backend/server.ts"] += "app.get('/auth/session', (req,res) => res.json({}));\n"
    tools = tools_for(tmp_path, applications)
    result, _ = run_plan(tools, max_planned_investigations=15)
    tasks = [task for task in result.plan.investigations if any(link.client.path.startswith("frontend/") for link in task.structural_signal.integration_links)]
    assert len(tasks) == 2
    assert_grounded(result, tools)


@pytest.mark.parametrize("scope", ["frontend/fixtures", "backend/ai-providers.integration.test.ts"])
def test_explicit_test_and_fixture_scopes_are_honored(tmp_path, applications, scope):
    tools = tools_for(tmp_path, applications)
    result, _ = run_plan(tools, request=AuditRequest(targets=[scope]))
    assert result.plan.investigations
    assert any(path == scope or path.startswith(scope + "/") for task in result.plan.investigations for path in task.scope)
    assert_grounded(result, tools)


def test_exclusive_boundary_scope_and_inferred_interfaces_are_not_automatically_preferred(tmp_path, applications):
    tools = tools_for(tmp_path, applications)
    result, _ = run_plan(tools)
    for task in result.plan.investigations:
        text = " ".join([task.question, *task.evidence_needed]).lower()
        assert not any(word in text for word in ("cohesion", "responsibilities", "change propagation", "change impact", "reuse", "coupling complexity"))
    task = result.plan.investigations[0]
    inferred = task.model_copy(update={"structural_signal": task.structural_signal.model_copy(update={"kind": "encapsulation", "basis": "inferred"})})
    corroborated = task.model_copy(update={"structural_signal": task.structural_signal.model_copy(update={"kind": "cycle", "basis": "corroborated"})})
    assert candidate_rank(corroborated) < candidate_rank(inferred)


def test_type_only_cycle_is_not_a_runtime_cycle(tmp_path):
    tools = tools_for(tmp_path, {"a.ts": "import type {B} from './b'; export interface A { b: B }\n",
        "b.ts": "import type {A} from './a'; export interface B { a: A }\n"})
    result, _ = run_plan(tools)
    assert len(result.plan.investigations) == 1
    task = result.plan.investigations[0]
    assert task.priority == "low" and task.structural_signal.basis == "inferred"
    assert all(ref.kind == "type_only" for ref in task.structural_signal.relationships)
    assert_grounded(result, tools)


def test_cycle_and_minority_direction_of_same_boundary_are_deduplicated(tmp_path):
    contents = {"alpha/main.py": "from beta.run import f\ndef f(): pass\n",
        "beta/run.py": "from alpha.main import f\ndef f(): pass\n"}
    for index in range(3):
        contents[f"alpha/extra{index}.py"] = f"from beta.worker{index} import f\n"
        contents[f"beta/worker{index}.py"] = "def f(): pass\n"
    tools = tools_for(tmp_path, contents)
    result, _ = run_plan(tools)
    assert len(result.plan.investigations) == 1
    assert result.plan.investigations[0].structural_signal.kind == "cycle"
    assert result.investigation_coverage["opportunities"]["deduplicated"] > 0
    assert_grounded(result, tools)


def test_scan_budget_disable_and_incomplete_index_are_reported(tmp_path, applications):
    tools = tools_for(tmp_path, applications)
    result, _ = run_plan(tools, max_integration_scan_files=1, max_integration_scan_characters=500)
    scan = result.investigation_coverage["integrations"]
    assert scan["scanned_files"] <= 1 and scan["scanned_characters"] <= 500 and scan["scan_omitted_files"] > 0
    assert any("dynamic wiring" in item for item in result.limitations)
    assert_grounded(result, tools)


def test_optional_structural_queries_are_bounded_and_cached_in_context(tmp_path):
    tools = tools_for(tmp_path, cycles(), limits=ToolLimits(max_metadata_items=3))
    model = PlanningModel(lambda context: {"opportunity_ids": [context["opportunities"][0]["id"]],
        "discovery_queries": [{"tool": "find_symbols", "arguments": {"file_path": "parts0/a.py", "limit": 500}}]})
    result, model = run_plan(tools, model, max_tool_calls=1)
    assert result.tool_calls == 1 and result.model_calls == 2
    assert model.contexts[1]["discovery_results"][0]["arguments"]["limit"] == 3
    assert any("redundant" in item for item in result.limitations)
    assert_grounded(result, tools)


def test_invalid_selection_and_model_calls_fail_closed(tmp_path):
    tools = tools_for(tmp_path, cycles())
    result, _ = run_plan(tools, PlanningModel(lambda _: {"opportunity_ids": ["invented"]}), max_schema_retries=0)
    assert result.termination_reason == "model_or_schema_error" and result.model_calls == 1
    assert not result.plan.investigations
    assert_grounded(result, tools)


def test_token_admission_is_preserved(tmp_path, finite_token_budget):
    tools = tools_for(tmp_path, cycles())
    result, model = run_plan(tools, max_total_tokens=1000)
    assert result.termination_reason == "token_limit" and not model.contexts
    assert result.model_calls == 0 and result.accounted_tokens == 0


def test_planning_timeout_does_not_become_success(tmp_path, monkeypatch):
    from server.agents.maintainability.modularity.architecture_boundary.execution import (
        BoundaryExecution,
    )

    def expired(self):
        raise TimeoutError

    tools = tools_for(tmp_path, cycles())
    monkeypatch.setattr(BoundaryExecution, "_check_planning", expired)
    result, model = run_plan(tools)
    assert result.termination_reason == "time_limit" and not model.contexts
    assert result.model_calls == result.tool_calls == result.accounted_tokens == 0
    assert not result.plan.investigations


def test_local_configuration_defaults_levels_and_parent_compatibility(tmp_path):
    config = validate_developer_agent_config("architecture_boundary", {"max_planned_investigations": 15})
    assert isinstance(config, BoundaryConfig) and config.max_planned_investigations == 15
    assert BoundaryConfig().max_planned_investigations == 12
    assert "max_planned_investigations" not in describe_agent_config("architecture_boundary")["config_schema"]["properties"]
    with pytest.raises(ValidationError):
        BoundaryConfig(max_planned_investigations=16)
    tools = tools_for(tmp_path, cycles())
    agent = ArchitectureBoundaryAgent(PlanningModel(), InvestigationConfig())
    result = asyncio.run(agent.run(tools))
    assert result.plan.investigations
    assert_grounded(result, tools)


def test_same_candidates_reordered_are_not_reported_as_replacements(tmp_path):
    tools = tools_for(tmp_path, cycles(count=3))
    model = PlanningModel(lambda context: {"opportunity_ids": [task["id"] for task in reversed(context["opportunities"])]})
    result, _ = run_plan(tools, model)
    assert not result.investigation_coverage["selection_rebalanced"]
    assert result.investigation_coverage["selection_added_ids"] == result.investigation_coverage["selection_removed_ids"] == []


def test_graph_connects_investigation_without_synthesis_and_runner_preserves_json_contract(tmp_path):
    tools = tools_for(tmp_path, cycles())
    agent = ArchitectureBoundaryAgent(PlanningModel())
    execution = agent.execution_type(agent.model, agent.config, tools, AuditRequest())
    assert set(execution.graph.get_graph().nodes) == {START, "plan_investigation", "investigate", "tools", END}
    result, _ = run_plan(tools)
    path = Path(__file__).parents[1] / "src/test-agents/run_architecture_boundary.py"
    spec = importlib.util.spec_from_file_location("boundary_runner", path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    text = runner.render_boundary_plan(result)
    assert "PLAN DE INVESTIGACIÓN" in text and "Condición de cierre" in text and "Hallazgos: no evaluados" in text
    assert_grounded(result, tools)
