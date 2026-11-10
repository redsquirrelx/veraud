"""Standalone planning runner: no provider calls or subordinate executions."""

import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_maintainability_v2_plan_audit import Model, assignment, capability, plan

from server.agents.maintainability.v2.manager import (
    AuditPlan,
    AuditResult,
    MaintainabilityRequest,
)
from server.agents.maintainability.v2.manager.config import MaintainabilityConfig


@pytest.fixture
def runner(monkeypatch):
    path = Path(__file__).parents[1] / "src/test-agents/run_maintainability_manager_v2.py"
    monkeypatch.syspath_prepend(str(path.parent))
    spec = importlib.util.spec_from_file_location("manager_v2_runner", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_prompt_required_and_repeatable_scope_constraints(runner):
    with pytest.raises(SystemExit):
        runner.parser().parse_args(["repo"])
    args = runner.parser().parse_args(["repo", "--prompt", "Audit Checkout", "--target", "Checkout",
        "--target", "Shared", "--constraint", "Read only", "--constraint", "No network"])
    assert args.prompt == "Audit Checkout"
    assert args.target == ["Checkout", "Shared"]
    assert args.constraint == ["Read only", "No network"]


@pytest.mark.parametrize("empty_catalog", [False, True])
def test_stops_at_plan_and_overwrites_canonical_output(runner, tmp_path, capsys, empty_catalog):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "api.py").write_text("class API: pass\n", encoding="utf-8")
    output = tmp_path / "plan.json"
    output.write_text("old result", encoding="utf-8")
    args = runner.parser().parse_args([str(root), "--prompt", "Analyze architecture", "--target", "api.py",
        "--constraint", "Read only", "--output-file", str(output), "--plan-only"])
    model = Model(plan(uncovered_requirements=["No relevant coordinator available."]) if empty_catalog else plan(assignment()))

    class Tracing:
        async def wrap_stage(self, operation, **metadata):
            assert metadata["name"] == "plan_audit"
            return await operation

    request = MaintainabilityRequest(objective=args.prompt, targets=args.target, constraints=args.constraint)
    state = asyncio.run(runner.run_plan(args, request, [] if empty_catalog else [capability()],
        MaintainabilityConfig(provider_request_interval_seconds=0), model, SimpleNamespace(max_tokens=1800),
        tracing_backend=Tracing()))
    data = json.loads(output.read_text(encoding="utf-8"))
    restored = AuditPlan.model_validate(data["plan"])
    assert restored == state["plan"]
    assert data["request"]["objective"] == args.prompt
    assert data["consumption"]["model_calls"] == len(model.contexts) == 1
    assert data["consumption"]["tool_calls"] == 0
    assert not data["termination_reason"]
    assert "sin delegaciones ni investigaciones" in capsys.readouterr().out
    if not empty_catalog:
        assert restored.assignments[0].scope == ["api.py"]
        assert "Read only" in restored.assignments[0].constraints
    assert (root / "api.py").read_text(encoding="utf-8") == "class API: pass\n"


def test_run_loads_capabilities_and_closes_model_on_failure(runner, tmp_path, monkeypatch):
    source = tmp_path / "capabilities.json"
    source.write_text(json.dumps([capability().model_dump()]), encoding="utf-8")
    args = runner.parser().parse_args(["repo", "--prompt", "Audit", "--capabilities", str(source)])
    model, closed = object(), []
    monkeypatch.setattr(runner, "load_test_model", lambda key: (model, SimpleNamespace(max_tokens=1800)))

    async def fail(args, request, capabilities, config, model, settings, **kwargs):
        assert capabilities == [capability()]
        raise RuntimeError("fixture failure")

    async def close(wrapper):
        closed.append(wrapper.llm)

    monkeypatch.setattr(runner, "run_plan", fail)
    monkeypatch.setattr(runner, "close_model_clients", close)
    with pytest.raises(RuntimeError, match="fixture failure"):
        asyncio.run(runner.run(args))
    assert closed == [model]


def test_runner_uses_registered_modularity_when_capabilities_omitted(runner, monkeypatch):
    args = runner.parser().parse_args(["repo", "--prompt", "Investiga problemas arquitectónicos en Checkout"])
    model = object()
    monkeypatch.setattr(runner, "load_test_model", lambda key: (model, SimpleNamespace(max_tokens=1800)))

    async def inspect(args, request, capabilities, config, model, settings, **kwargs):
        assert [item.id for item in capabilities] == ["modularity"]
        assert request.objective == args.prompt
        return "planning-only"

    async def close(wrapper):
        assert wrapper.llm is model

    monkeypatch.setattr(runner, "run_plan", inspect)
    monkeypatch.setattr(runner, "close_model_clients", close)
    assert asyncio.run(runner.run(args)) == "planning-only"


def test_runner_loads_canonical_context_for_transport_without_changing_scope(runner, tmp_path, monkeypatch):
    from test_architecture_boundary_doc_driven_investigation import verified_tools
    from test_architecture_boundary_doc_driven_planning import claim, context

    tools = verified_tools(tmp_path, {"app/api.py": "class API: pass\n"})
    documented = context(tools, [claim()])
    source = tmp_path / "canonical-context.txt"
    source.write_text(documented.model_dump_json(), encoding="utf-8")
    args = runner.parser().parse_args([str(tmp_path / "repo"), "--prompt", "Inspect boundaries", "--target", "app",
                                     "--architecture-context", str(source)])
    model = object()
    monkeypatch.setattr(runner, "load_test_model", lambda key: (model, SimpleNamespace(max_tokens=1800)))

    async def inspect(args, request, *others, **kwargs):
        assert request.documented_architecture == documented
        assert request.targets == ["app"]
        assert request.objective == "Inspect boundaries"
        return "transported"

    async def close(wrapper):
        assert wrapper.llm is model

    monkeypatch.setattr(runner, "run_plan", inspect)
    monkeypatch.setattr(runner, "close_model_clients", close)
    assert asyncio.run(runner.run(args)) == "transported"


def test_runner_rejects_noncanonical_context_before_constructing_a_model(runner, tmp_path, monkeypatch):
    source = tmp_path / "invalid-context.txt"
    source.write_text('{"architecture_context": "narrative substitute"}', encoding="utf-8")
    args = runner.parser().parse_args(["repo", "--prompt", "Inspect boundaries", "--architecture-context", str(source)])
    monkeypatch.setattr(runner, "load_test_model", lambda *args: pytest.fail("Invalid context must fail before model construction"))
    with pytest.raises(ValueError):
        asyncio.run(runner.run(args))


def test_runner_default_reaches_finalize_and_serializes_final_result(runner, tmp_path, capsys):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "api.py").write_text("class API: pass\n", encoding="utf-8")
    destination = tmp_path / "audit.json"
    args = runner.parser().parse_args([str(root), "--prompt", "Unsupported capability", "--output-file", str(destination)])
    model = Model(plan(uncovered_requirements=["No compatible coordinator."]))

    class Tracing:
        async def wrap_stage(self, operation, **metadata):
            return await operation

    result = asyncio.run(runner.run_plan(args, MaintainabilityRequest(objective=args.prompt), [],
        MaintainabilityConfig(provider_request_interval_seconds=0), model, SimpleNamespace(max_tokens=1800), tracing_backend=Tracing()))
    assert AuditResult.model_validate_json(destination.read_text(encoding="utf-8")) == result
    assert result.status == "not_applicable" and result.node_transitions[-1] == "finalize_audit"
    assert result.consumption.model_calls == 1 and "Sin coordinadores aplicables" in capsys.readouterr().out
