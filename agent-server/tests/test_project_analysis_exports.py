"""Project-analysis configuration exports retain their canonical identities."""

from importlib import import_module

import pytest


@pytest.mark.parametrize(("stage", "name"), [
    ("project_architecture", "ArchitectureLimits"),
    ("project_orientation", "OrientationLimits"),
    ("project_semantic_validation", "ValidationLimits"),
])
def test_limits_exports_are_the_canonical_configuration_classes(stage, name):
    package = f"server.project_analysis.{stage}"
    canonical = getattr(import_module(f"{package}.config"), name)

    assert getattr(import_module(f"{package}.schemas"), name) is canonical
    assert getattr(import_module(package), name) is canonical
