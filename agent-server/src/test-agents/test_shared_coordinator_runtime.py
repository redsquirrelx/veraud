"""Shared orchestration is independent of concrete audit dimensions."""

import ast
from importlib.util import resolve_name
from pathlib import Path

from server.agents.maintainability.manager.agent import MaintainabilityManagerExecution
from server.agents.maintainability.modularity.coordinator.agent import (
    ModularityAgent,
    ModularityExecution,
)
from server.agents.maintainability.modularity.coordinator.schemas import (
    Consumption as LegacyConsumption,
)
from server.agents.maintainability.reusability.coordinator.agent import (
    ReusabilityAgent,
    ReusabilityExecution,
)
from server.runtimes.coordination.execution import (
    CoordinatorAgent,
    CoordinatorExecution,
)
from server.runtimes.coordination.schemas import Consumption


def test_sibling_agents_and_manager_share_a_neutral_execution_not_a_modularity_base():
    executions = (ModularityExecution, ReusabilityExecution, MaintainabilityManagerExecution)
    assert all(issubclass(cls, CoordinatorExecution) for cls in executions)
    assert all(not issubclass(left, right) for left in executions for right in executions if left is not right)
    assert issubclass(ModularityAgent, CoordinatorAgent) and issubclass(ReusabilityAgent, CoordinatorAgent)
    assert not issubclass(ReusabilityAgent, ModularityAgent) and not issubclass(ModularityAgent, ReusabilityAgent)
    assert Consumption is LegacyConsumption


def test_runtime_and_shared_configuration_do_not_import_concrete_agents():
    import config.agents as config_package
    import server.runtimes as runtime_package

    for package in (config_package, runtime_package):
        root = Path(package.__file__).parent
        for path in root.rglob("*.py"):
            relative = path.relative_to(root).with_suffix("").parts
            parent = ".".join((package.__name__, *relative[:-1]))
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if node.level:
                        module = resolve_name("." * node.level + module, parent)
                    assert module != "server.agents" and not module.startswith("server.agents."), path
                    components = set((node.module or "").split("."))
                    assert not components & {"maintainability", "project_analysis", "security", "functional_adequacy"}, path
                elif isinstance(node, ast.Import):
                    assert all(
                        alias.name != "server.agents" and not alias.name.startswith("server.agents.")
                        for alias in node.names
                    ), path


def test_repository_config_imports_are_aliases_to_canonical_shared_owners():
    from config.agents import ExecutionBudget, ToolLimits
    from server.runtimes.repository.schemas import (
        ExecutionBudget as RuntimeBudget,
    )
    from server.runtimes.repository.tools import ToolLimits as RuntimeToolLimits

    assert RuntimeBudget is ExecutionBudget and RuntimeToolLimits is ToolLimits
    assert ExecutionBudget.__module__ == "config.agents.repository_execution"
    assert ToolLimits.__module__ == "config.agents.tools"
