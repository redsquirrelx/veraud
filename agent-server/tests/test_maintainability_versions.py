"""Version placement must not register V2 or make it depend on V1."""

import subprocess
import sys
from importlib import import_module, resources

import pytest


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_boundary_version_owns_its_contracts_and_prompt_resources(version):
    package = f"server.agents.maintainability.{version}.modularity.architecture_boundary"
    boundary = import_module(package)
    assert boundary.ArchitectureBoundaryAgent.request_type is boundary.AuditRequest
    assert boundary.ArchitectureBoundaryAgent.config_type is boundary.BoundaryConfig
    assert boundary.AuditRequest.__module__ == f"{package}.schemas"
    assert boundary.BoundaryConfig.__module__ == f"{package}.config"
    for name in ("plan_investigation.md", "investigate.md"):
        assert resources.files(package).joinpath("prompts", name).read_text(encoding="utf-8").strip()


def test_boundary_v2_imports_without_v1_and_production_stays_on_v1():
    # A fresh interpreter catches accidental imports hidden by pytest collection.
    subprocess.run([sys.executable, "-c", """
import sys
from server.agents.maintainability.v2.modularity.architecture_boundary import ArchitectureBoundaryAgent
assert not any(name.startswith('server.agents.maintainability.v1') for name in sys.modules)
"""], check=True, capture_output=True, text=True)
    subprocess.run([sys.executable, "-c", """
import sys
from config.agents.catalog import AGENT_CONFIGS, configuration_type
from server.agents.maintainability.v1.manager.registry import COORDINATORS
from server.agents.maintainability.v1.modularity.coordinator.registry import INVESTIGATORS as modularity
from server.agents.maintainability.v1.reusability.coordinator.registry import INVESTIGATORS as reusability
for spec in [*COORDINATORS.values(), *modularity.values(), *reusability.values()]:
    assert spec.agent_class.__module__.startswith('server.agents.maintainability.v1.')
for identifier in AGENT_CONFIGS:
    configuration_type(identifier)
assert not any(name.startswith('server.agents.maintainability.v2') for name in sys.modules)
"""], check=True, capture_output=True, text=True)
