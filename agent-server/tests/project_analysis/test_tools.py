"""Workspace isolation, documentation policy, bounded delivery, and provenance."""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from server.agents.project_analysis import (
    InvestigationBudget,
    ProjectAnalysisContext,
    ProjectAnalysisInput,
    RepositoryToolset,
    ToolLimits,
)
from server.agents.project_analysis.access import RepositoryAccessError
from server.agents.project_analysis.schemas import (
    AnalysisClaim,
    InvestigationCoverage,
    InvestigationObjective,
    InvestigationPlan,
    ProjectAnalysisReport,
    RetrievedEvidence,
)
from server.services.repository_analysis import RepositoryAnalysisService


def write_files(root, files):
    for relative_path, content in files.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


@pytest.fixture
def checkout(tmp_path):
    workspace = tmp_path / "workspace"
    root = workspace / "selected"
    write_files(
        root,
        {
            "pyproject.toml": '[project]\nname="selected"\ndependencies=["fastapi>=0.100"]\n',
            "src/main.py": 'from fastapi import FastAPI\napp = FastAPI()\n@app.get("/items")\ndef items():\n    return "SOURCE_ONLY"\n',
            "src/architecture.py": "class Component:\n    pass\n",
            "tests/test_main.py": "def test_items():\n    assert True\n",
            "Dockerfile": "FROM python:3.13\n",
            "compose.yaml": "services:\n  database:\n    image: postgres:16\n",
            "requirements-dev.txt": "pytest>=8\n",
            "README.md": "NARRATIVE_ONLY: This project uses unicorn storage.\n",
            "README.py": 'def misleading():\n    return "NARRATIVE_ONLY"\n',
            "docs/hidden.py": 'def undocumented():\n    return "NARRATIVE_ONLY"\n',
            "architecture.json": '{"claim":"NARRATIVE_ONLY"}',
            "notes.txt": "NARRATIVE_ONLY\n",
            ".env": "PRIVATE_VALUE=hidden\n",
        },
    )
    write_files(workspace / "sibling", {"outside.py": 'VALUE = "SIBLING_ONLY"\n'})
    snapshot = RepositoryAnalysisService().analyze_sync(root)
    return workspace, root, snapshot


def toolset(checkout, *, budget=None, limits=None):
    workspace, _, snapshot = checkout
    context = ProjectAnalysisContext(
        snapshot=snapshot,
        input=ProjectAnalysisInput(
            snapshot_hash=snapshot.repository.snapshot_hash,
            budget=budget or InvestigationBudget(),
        ),
    )
    return RepositoryToolset(context, workspace_root=workspace, limits=limits)


def call(tools, name, /, **arguments):
    return tools.execute(
        name, arguments, tool_call_id=f"call-{tools.budget_usage.tool_calls + 1}"
    )


def test_tool_telemetry_detects_repeats_with_defaults_without_retaining_content(
    checkout,
):
    tools = toolset(checkout)
    first = call(tools, "list_files")
    second = call(tools, "list_files", offset=0, limit=20)
    assert first.status == second.status == "ok"
    records = tools.tool_measurements
    assert len(records) == 2 and not records[0].repeated and records[1].repeated
    assert records[0].request_sha256 == records[1].request_sha256
    assert "src/main.py" not in records[0].model_dump_json()
    call(tools, "get_source_excerpt", path="src/main.py")
    assert "SOURCE_ONLY" not in tools.tool_measurements[-1].model_dump_json()
    before = len(tools.tool_measurements)
    tools.execute("list_files", {}, tool_call_id=first.tool_call_id)
    assert len(tools.tool_measurements) == before


def report_with_claim(tools, claim, retrievals=()):
    snapshot = tools.context.snapshot
    source = next(source for source in snapshot.files if source.path == "src/main.py")
    objective = InvestigationObjective(
        id="investigation:main",
        project_id=source.project_id,
        objective="Inspect main.",
        seed_entity_ids=(source.id,),
        questions=("What does main expose?",),
        report_sections=("main_flows",),
        selection_reason="Application entrypoint.",
        priority_tier="startup",
        expected_deliverable="An inspected startup path.",
        completion_criteria=("Inspect source.",),
    )
    return ProjectAnalysisReport(
        snapshot_hash=snapshot.repository.snapshot_hash,
        investigation_plan=InvestigationPlan(objectives=(objective,)),
        claims=(claim,),
        retrieved_evidence=retrievals,
        investigation_coverage=InvestigationCoverage(
            planned_investigation_ids=(objective.id,),
            pending_investigation_ids=(objective.id,),
        ),
    )


def test_tools_are_bound_to_one_checkout_not_the_workspace_or_another_root(
    checkout, tmp_path
):
    tools = toolset(checkout)
    assert tools.policy.repository_root == checkout[1].resolve()
    outside = tmp_path / "outside"
    write_files(outside, {"main.py": "VALUE = 1\n"})
    snapshot = RepositoryAnalysisService().analyze_sync(outside)
    context = ProjectAnalysisContext(
        snapshot=snapshot,
        input=ProjectAnalysisInput(snapshot_hash=snapshot.repository.snapshot_hash),
    )
    with pytest.raises(RepositoryAccessError, match="directly inside"):
        RepositoryToolset(context, workspace_root=checkout[0])
    root_snapshot = RepositoryAnalysisService().analyze_sync(checkout[0])
    with pytest.raises(RepositoryAccessError):
        RepositoryToolset(
            ProjectAnalysisContext(
                snapshot=root_snapshot,
                input=ProjectAnalysisInput(
                    snapshot_hash=root_snapshot.repository.snapshot_hash
                ),
            ),
            workspace_root=checkout[0],
        )
    response = call(tools, "get_source_excerpt", path="outside.py")
    assert response.error.code == "access_denied"
    assert (
        call(tools, "search_repository_text", query="SIBLING_ONLY").data["total"] == 0
    )


@pytest.mark.parametrize(
    "path",
    [
        "../sibling/outside.py",
        "/etc/passwd",
        "C:\\Windows\\system.ini",
        "\\\\server\\share\\file.py",
        "src/main.py:stream",
        "file:///outside.py",
        "src/../../outside.py",
        "src/\x00main.py",
    ],
)
def test_paths_cannot_escape_the_selected_checkout(checkout, path):
    tools = toolset(checkout)
    for name, arguments in [
        ("get_source_excerpt", {"path": path}),
        ("find_symbols", {"file_path": path}),
        ("list_files", {"path_prefix": path}),
        ("search_repository_text", {"query": "VALUE", "path_prefix": path}),
    ]:
        response = call(tools, name, **arguments)
        assert response.status == "error"
        assert response.error.code == "access_denied"
    assert not tools.retrieved_evidence


def test_documentation_is_filtered_before_search_pagination_and_indirect_retrieval(
    checkout,
):
    tools = toolset(checkout)
    response = call(tools, "list_files", limit=50)
    paths = {item["path"] for item in response.data["items"]}
    assert {
        "src/main.py",
        "src/architecture.py",
        "tests/test_main.py",
        "pyproject.toml",
        "Dockerfile",
    } <= paths
    assert (
        not {
            "README.md",
            "README.py",
            "docs/hidden.py",
            "notes.txt",
            "architecture.json",
            ".env",
        }
        & paths
    )
    assert all("content" not in item for item in response.data["items"])
    assert response.data["total"] == len(paths)
    assert (
        call(tools, "search_repository_text", query="NARRATIVE_ONLY").data["total"] == 0
    )
    assert call(tools, "find_symbols", name="misleading").data["total"] == 0
    hidden_symbol = next(
        symbol
        for symbol in tools.context.snapshot.symbols
        if symbol.name == "misleading"
    )
    hidden_evidence = hidden_symbol.evidence_ids[0]
    for name, arguments in [
        ("get_source_excerpt", {"path": "README.md"}),
        ("get_symbol_source", {"symbol_id": hidden_symbol.id}),
        ("get_evidence", {"evidence_id": hidden_evidence}),
        ("get_outgoing_relationships", {"entity_id": hidden_symbol.file_id}),
    ]:
        assert call(tools, name, **arguments).error.code == "access_denied"


def test_every_query_adapter_works_and_preserves_reference_scope(checkout):
    tools = toolset(checkout)
    snapshot = tools.context.snapshot
    symbol = next(symbol for symbol in snapshot.symbols if symbol.name == "items")
    for name, arguments in [
        ("get_repository_overview", {}),
        ("list_projects", {}),
        ("list_files", {}),
        ("find_symbols", {"name": "items"}),
        ("get_dependencies", {"name": "fastapi"}),
        ("list_relationships", {}),
        ("get_outgoing_relationships", {"entity_id": symbol.file_id}),
        ("get_incoming_relationships", {"entity_id": symbol.id}),
        ("list_entrypoints", {}),
        ("get_infrastructure", {}),
        ("get_testing_configuration", {}),
        ("get_evidence", {"evidence_id": symbol.evidence_ids[0]}),
        ("get_symbol_source", {"symbol_id": symbol.id}),
    ]:
        response = call(tools, name, **arguments)
        assert response.status == "ok", response.error
        assert response.snapshot_hash == snapshot.repository.snapshot_hash
    overview = call(tools, "get_repository_overview").data
    assert overview["access_policy"]["scope"] == "selected_workspace_checkout"
    assert overview["access_policy"]["omitted_files"] >= 5
    assert (
        tools.initial_state()["repository_overview"].file_count
        == overview["file_count"]
    )


def test_source_ranges_remain_exact_and_queries_never_read_live_files(checkout):
    tools = toolset(checkout, limits=ToolLimits(max_source_lines=2))
    (checkout[1] / "src/main.py").unlink()
    first = call(
        tools, "get_source_excerpt", path="src\\main.py", start_line=1, end_line=5
    )
    assert first.status == "ok"
    assert first.data["end_line"] == 2 and first.data["requested_end_line"] == 5
    assert first.data["truncated"] is True
    assert first.data["content"] == "from fastapi import FastAPI\napp = FastAPI()"
    assert len(first.evidence) == 1 and first.evidence[0].end_line == 2
    second = call(
        tools, "get_source_excerpt", path="src/main.py", start_line=3, end_line=5
    )
    assert second.data["start_line"] == 3 and second.data["end_line"] == 4
    invalid = call(
        tools, "get_source_excerpt", path="src/main.py", start_line=1, end_line=99
    )
    assert invalid.error.code == "invalid_source_range"


def test_search_delivers_line_evidence_while_metadata_does_not_claim_source_inspection(
    checkout,
):
    tools = toolset(checkout)
    metadata = call(tools, "find_symbols", name="items")
    assert metadata.evidence and all(
        item.kind == "metadata" for item in metadata.evidence
    )
    search = call(tools, "search_repository_text", query="SOURCE_ONLY")
    assert search.data["total"] == 1
    assert search.evidence[0].kind == "source" and search.evidence[0].start_line == 5
    assert search.evidence[0].end_line == 5


def test_tool_call_budget_includes_invalid_requests_and_is_atomic(checkout):
    tools = toolset(checkout, budget=InvestigationBudget(max_tool_calls=2))
    assert call(tools, "get_source_excerpt", path="missing.py").status == "error"
    assert call(tools, "list_files").status == "ok"
    assert call(tools, "list_files").error.code == "tool_budget_exhausted"
    assert tools.budget_usage.tool_calls == 2
    concurrent = toolset(checkout, budget=InvestigationBudget(max_tool_calls=1))
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(
            executor.map(
                lambda identifier: concurrent.execute(
                    "list_files", {}, tool_call_id=identifier
                ),
                ("one", "two"),
            )
        )
    assert sorted(response.status for response in responses) == ["error", "ok"]
    assert concurrent.budget_usage.tool_calls == 1


def test_content_budget_and_response_limits_register_only_delivered_evidence(checkout):
    tools = toolset(checkout, budget=InvestigationBudget(max_retrieved_characters=512))
    response = call(tools, "get_source_excerpt", path="src/main.py")
    assert response.error.code == "content_budget_exhausted"
    assert tools.budget_usage.retrieved_characters == 0
    assert tools.retrieved_evidence == ()
    bounded = toolset(checkout, limits=ToolLimits(max_response_characters=3000))
    response = call(bounded, "list_files", limit=20)
    assert response.status == "ok"
    assert len(response.model_dump_json()) <= 3000
    assert response.data["truncated"] is True
    assert response.data["next_offset"] == len(response.data["items"])
    delivered_ids = {item["id"] for item in response.data["items"]}
    assert all(record.file_id in delivered_ids for record in response.evidence)
    assert bounded.budget_usage.retrieved_characters == len(response.model_dump_json())


def test_invalid_arguments_unknown_tools_and_replayed_call_ids_are_controlled(checkout):
    tools = toolset(checkout)
    for name, arguments in [
        ("list_files", {"root_path": str(checkout[0] / "sibling")}),
        ("list_files", {"offset": -1}),
        ("list_files", {"limit": "10"}),
        ("search_repository_text", {"query": "VALUE", "case_sensitive": "false"}),
    ]:
        assert call(tools, name, **arguments).error.code == "invalid_arguments"
    assert call(tools, "read_file", path="src/main.py").error.code == "unknown_tool"
    assert call(tools, "list_files", limit=51).error.code == "page_limit_exceeded"
    response = tools.execute("list_projects", {}, tool_call_id="same")
    assert response.status == "ok"
    assert (
        tools.execute("list_projects", {}, tool_call_id="same").error.code
        == "duplicate_tool_call_id"
    )


def test_time_budget_prevents_delivery(checkout, monkeypatch):
    from server.agents.project_analysis import context as context_module

    tools = toolset(checkout, budget=InvestigationBudget(max_elapsed_seconds=1))
    monkeypatch.setattr(
        context_module, "monotonic", lambda: tools.context.started_at + 2
    )
    response = call(tools, "list_files")
    assert response.error.code == "time_budget_exhausted"
    assert tools.retrieved_evidence == ()


def test_report_citations_must_have_been_delivered_and_cannot_be_forged(checkout):
    tools = toolset(checkout)
    response = call(
        tools, "get_source_excerpt", path="src/main.py", start_line=3, end_line=5
    )
    evidence = response.evidence[0]
    claim = AnalysisClaim(
        id="claim:items",
        statement="The handler returns SOURCE_ONLY.",
        status="supported",
        evidence_ids=(evidence.id,),
    )
    draft = report_with_claim(tools, claim, (evidence,))
    tools.validate_report_access(draft)
    forged = RetrievedEvidence(**(evidence.model_dump() | {"tool_call_id": "invented"}))
    with pytest.raises(RepositoryAccessError, match="not delivered"):
        tools.validate_report_access(report_with_claim(tools, claim, (forged,)))
    symbol = next(
        symbol for symbol in tools.context.snapshot.symbols if symbol.name == "items"
    )
    uninspected = AnalysisClaim(
        id="claim:items",
        statement="The handler returns SOURCE_ONLY.",
        status="supported",
        evidence_ids=symbol.evidence_ids,
    )
    with pytest.raises(RepositoryAccessError, match="not delivered"):
        tools.validate_report_access(report_with_claim(tools, uninspected))


def test_langchain_tool_schemas_cannot_select_another_workspace(checkout):
    tools = toolset(checkout)
    adapters = {tool.name: tool for tool in tools.as_langchain_tools()}
    for tool in adapters.values():
        assert "root_path" not in tool.args and "workspace_root" not in tool.args
    response = adapters["get_source_excerpt"].invoke(
        {"path": "src/main.py", "start_line": 5, "end_line": 5}
    )
    assert "SOURCE_ONLY" in response
    assert tools.retrieved_evidence[-1].kind == "source"
    rejected = json.loads(adapters["list_files"].invoke({"root_path": "../sibling"}))
    assert rejected["error"]["code"] == "invalid_arguments"
    assert tools.budget_usage.tool_calls == 2


def test_large_source_and_nested_metadata_omissions_are_explicit(checkout):
    limited = toolset(
        checkout, limits=ToolLimits(max_source_characters=10, max_metadata_items=1)
    )
    assert (
        call(limited, "get_source_excerpt", path="src/main.py").error.code
        == "source_limit_exceeded"
    )
    assert not limited.retrieved_evidence
    overview = call(limited, "get_repository_overview")
    assert overview.status == "ok"
    assert len(overview.data["technologies"]) == 1
    assert overview.data["omitted_field_items"]["technologies"] > 0


def test_poisoned_snapshot_paths_and_cross_checkout_evidence_are_rejected(checkout):
    workspace, _, snapshot = checkout
    unsafe_file = snapshot.files[0].model_copy(update={"path": "../sibling/outside.py"})
    poisoned = snapshot.model_copy(update={"files": (unsafe_file,)})
    context = ProjectAnalysisContext(
        snapshot=poisoned,
        input=ProjectAnalysisInput(snapshot_hash=poisoned.repository.snapshot_hash),
    )
    with pytest.raises(RepositoryAccessError, match="traversal"):
        RepositoryToolset(context, workspace_root=workspace)
    sibling = RepositoryAnalysisService().analyze_sync(workspace / "sibling")
    tools = toolset(checkout)
    sibling_evidence = sibling.evidence
    # A sibling with only an assignment may have no extracted evidence; a foreign
    # file ID is still not accepted as a relationship/source origin.
    assert (
        call(
            tools, "get_outgoing_relationships", entity_id=sibling.files[0].id
        ).error.code
        == "access_denied"
    )
    for evidence in sibling_evidence:
        assert (
            call(tools, "get_evidence", evidence_id=evidence.id).error.code
            == "access_denied"
        )
