"""The controlled corpus binds six distinct semantic failure modes to real source."""

from server.agents.project_analysis.project_semantic_validation.context import (
    review_targets,
    validate_input,
)
from server.benchmark.semantic_cases import build_semantic_cases
from server.repository_runner import make_tools
from server.runtimes.repository import ExecutionBudget


def test_six_cases_have_accessible_source_and_stable_targets(tmp_path):
    workspace = tmp_path / "workspace"
    snapshot, original, expected = build_semantic_cases(workspace)
    tools = make_tools(snapshot, ExecutionBudget(), workspace)
    validate_input(tools, original)
    targets = {target.id: target for target in review_targets(tools, original)}
    assert len(expected) == 6 and expected.keys() <= targets.keys()
    assert all(targets[key].source_hints for key in expected)
    assert "worker.py" in {source.path for source in tools.accessible_snapshot.files}
    assert all(
        "supported" not in verdicts
        for key, verdicts in expected.items()
        if key != "/organization/0/responsibility"
    )
    assert original.architecture.closest_architecture.scope_kind == "local"
