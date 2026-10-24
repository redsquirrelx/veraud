"""The user boundary exposes operating limits, never developer execution policy."""

import json
from inspect import get_annotations

import pytest
from pydantic import ValidationError

from config.agents.catalog import (
    configuration_type,
    describe_agent_config,
    list_agent_configs,
    validate_agent_config,
    validate_developer_agent_config,
)
from config.agents.levels import fields_for_level


@pytest.mark.parametrize("agent_id", list_agent_configs())
def test_default_panel_contains_only_user_fields_and_no_developer_payload(agent_id):
    panel = describe_agent_config(agent_id)
    runtime = configuration_type(agent_id)
    user = fields_for_level(runtime, "user")
    developer = fields_for_level(runtime, "developer")
    assert user.isdisjoint(developer)
    assert user | developer == set(runtime.model_fields)
    assert panel["level"] == "user"
    assert set(panel["config_schema"]["properties"]) == user
    assert set(panel["defaults"]) == user
    assert {name for names in panel["groups"].values() for name in names} == user
    payload = json.dumps(panel)
    for internal in ("tools", "prompts", "prompt_nodes", "prompt_defaults", "invocation_limits", "max_context_characters"):
        assert f'"{internal}"' not in payload
    assert validate_agent_config(agent_id, panel["defaults"]) == runtime()


@pytest.mark.parametrize("values", [
    {"tools": ["list_files"]},
    {"prompts": {"investigate": "replacement"}},
    {"max_iterations": 1},
    {"max_model_calls": 4},
    {"max_tool_calls": 1},
    {"max_output_tokens": 256},
    {"max_context_characters": 4000},
    {"max_provider_retries": 0},
    {"provider_request_interval_seconds": 0},
    {"provider_rate_limits": {"requests_per_minute": 10, "prompts": {}}},
])
def test_user_edits_reject_developer_fields_even_when_runtime_values_would_be_valid(values):
    with pytest.raises(ValidationError):
        validate_agent_config("responsibility", values)


@pytest.mark.parametrize("agent_id, values", [
    ("maintainability_manager", {"invocation_limits": {"max_total_tokens": 100_000}}),
    ("maintainability_manager", {"max_attempts_per_dimension": 3}),
    ("modularity", {"max_rounds": 3}),
    ("dependency_impact", {"max_dependency_depth": 2}),
    ("abstraction", {"max_candidates": 2}),
    ("reuse_opportunity", {"max_groups": 2}),
    ("component_adaptability", {"max_scan_files": 10}),
    ("project_architecture", {"soft_token_budgets": False}),
    ("project_semantic_validation", {"batch_size": 1}),
])
def test_specialized_investigation_and_delegation_tuning_is_developer_owned(agent_id, values):
    with pytest.raises(ValidationError):
        validate_agent_config(agent_id, values)
    assert validate_developer_agent_config(agent_id, values)


def test_user_edits_preserve_developer_policy_and_unedited_nested_quota():
    base = validate_developer_agent_config("responsibility", {
        "max_iterations": 2,
        "tools": ["list_files"],
        "prompts": {"investigate": "Developer research policy"},
        "provider_rate_limits": {"requests_per_minute": 9, "tokens_per_minute": 80_000},
    })
    resolved = validate_agent_config("responsibility", {
        "max_total_tokens": 150_000,
        "timeout_seconds": 450,
        "provider_rate_limits": {"requests_per_minute": None},
    }, base=base)
    assert resolved.max_total_tokens == 150_000 and resolved.timeout_seconds == 450
    assert resolved.provider_rate_limits.requests_per_minute is None
    assert resolved.provider_rate_limits.tokens_per_minute == 80_000
    assert resolved.max_iterations == base.max_iterations
    assert resolved.tools == base.tools and resolved.prompts == base.prompts
    assert base.max_total_tokens == 100_000 and base.provider_rate_limits.requests_per_minute == 9


@pytest.mark.parametrize("agent_id, budget, timeout", [
    ("responsibility", 100_000, 300),
    ("reusability", 300_000, 600),
    ("maintainability_manager", 1_000_000, 1200),
])
def test_user_schema_uses_effective_agent_defaults_and_quota_fields(agent_id, budget, timeout):
    panel = describe_agent_config(agent_id)
    assert panel["defaults"]["max_total_tokens"] == budget
    assert panel["defaults"]["timeout_seconds"] == timeout
    schema = panel["config_schema"]
    quota_ref = schema["properties"]["provider_rate_limits"]["$ref"].split("/")[-1]
    assert set(schema["$defs"][quota_ref]["properties"]) == {"requests_per_minute", "tokens_per_minute"}


def test_developer_view_is_explicit_and_labels_every_effective_field():
    panel = describe_agent_config("dependency_impact", level="developer")
    assert panel["level"] == "developer"
    assert panel["field_levels"]["max_total_tokens"] == "user"
    assert panel["field_levels"]["max_dependency_depth"] == "developer"
    assert panel["field_levels"]["prompts"] == panel["field_levels"]["tools"] == "developer"
    assert panel["prompt_defaults"]["investigate"]
    with pytest.raises(ValueError, match="Unknown configuration level"):
        describe_agent_config("dependency_impact", level="advanced")


def test_shared_configuration_fields_have_one_source_declaration():
    # Unrelated contracts may use the same name; consumers must not redeclare
    # fields already owned by one of their configuration bases.
    for cls in {configuration_type(agent_id) for agent_id in list_agent_configs()}:
        for name in cls.model_fields:
            owners = [base for base in cls.__mro__ if name in get_annotations(base)]
            assert len(owners) == 1, (cls.__name__, name, owners)


def test_presets_preserve_effective_bounds_and_do_not_mutate_shared_fields():
    from config.agents import InvestigationConfig
    from config.agents.budgets import TokenBudgetConfig
    from server.agents.maintainability.modularity.coordinator import (
        ModularityConfig,
    )
    from server.runtimes.repository.schemas import ExecutionBudget

    manager = configuration_type("maintainability_manager")
    assert TokenBudgetConfig().max_total_tokens == InvestigationConfig().max_total_tokens == 100_000
    assert ExecutionBudget().max_total_tokens == 60_000
    assert ModularityConfig().max_total_tokens == 300_000
    assert manager().max_total_tokens == 1_000_000
    assert isinstance(manager().invocation_limits, ModularityConfig)
    assert manager().model_json_schema()["properties"]["max_total_tokens"]["default"] == 1_000_000
    with pytest.raises(ValidationError):
        manager(max_parallel=3)
    with pytest.raises(ValidationError):
        ModularityConfig(max_invocations=2)
    with pytest.raises(ValidationError):
        InvestigationConfig(max_model_calls=101)
    with pytest.raises(ValidationError):
        configuration_type("project_orientation")(max_model_calls=5)
    with pytest.raises(ValidationError):
        configuration_type("project_architecture")(max_source_characters=399)


def test_user_contract_is_also_used_by_repository_execution_without_adding_fields():
    from config.agents.budgets import TokenBudgetConfig
    from server.runtimes.repository.schemas import ExecutionBudget

    assert issubclass(ExecutionBudget, TokenBudgetConfig)
    assert ExecutionBudget(max_total_tokens=180_000).max_total_tokens == 180_000
    assert "defaults" not in ExecutionBudget().model_dump()
