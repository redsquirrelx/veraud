"""Configuration ownership, panel contracts and actual runtime consumption (offline)."""

import asyncio
import importlib
import json

import pytest
from pydantic import ValidationError
from test_architecture_boundary import (
    PLAN,
    ScriptedModel,
    call,
    evaluation,
    request,
    review,
    toolset,
)

from config.agents import (
    CoordinatorConfig,
    InvestigationConfig,
    ModelSettings,
    ProviderRateLimits,
)
from config.agents.catalog import (
    AGENT_CONFIGS,
    configuration_type,
    describe_developer_agent_config,
    list_agent_configs,
    validate_developer_agent_config,
)


@pytest.mark.parametrize("agent_id", list_agent_configs())
def test_panel_descriptor_matches_actual_config_and_keeps_refs_self_contained(agent_id):
    description = describe_developer_agent_config(agent_id)
    cls = configuration_type(agent_id)
    spec = AGENT_CONFIGS[agent_id]
    schemas = importlib.import_module("server.agents." + spec.package + ".schemas")
    assert getattr(schemas, spec.config_name) is cls
    assert description["config_class"] == cls.__module__ + "." + cls.__name__
    assert validate_developer_agent_config(agent_id, description["defaults"]) == cls()
    assert json.loads(json.dumps(description)) == description
    groups = [field for group in description["groups"].values() for field in group]
    assert len(groups) == len(set(groups))
    assert set(groups) | set(description["hidden_fields"]) == set(cls.model_fields)
    assert set(description["specific_fields"]) <= set(groups)
    assert "api_key" not in json.dumps(description)
    assert all(description["prompt_defaults"][node].strip() for node in description["prompt_nodes"])
    schema = description["config_schema"]
    def validate_refs(value):
        if isinstance(value, dict):
            if "$ref" in value:
                assert value["$ref"].startswith("#/$defs/")
                assert value["$ref"].split("/")[-1] in schema["$defs"]
            for item in value.values():
                validate_refs(item)
        elif isinstance(value, list):
            for item in value:
                validate_refs(item)
    validate_refs(schema)


def test_local_configuration_is_a_single_file_only_for_agent_specific_policy():
    from pathlib import Path

    import config.agents
    import server.agents

    shared_root = Path(config.agents.__file__).parent
    agents_root = Path(server.agents.__file__).parent
    assert shared_root == agents_root.parents[2] / "config" / "agents"
    assert not list(agents_root.rglob("config/__init__.py"))
    assert not (agents_root / "config").exists()
    assert AGENT_CONFIGS["modularity"].shared_config is CoordinatorConfig
    assert AGENT_CONFIGS["reusability"].shared_config is CoordinatorConfig
    manager = configuration_type("maintainability_manager")
    assert manager.__module__ == "server.agents.maintainability.manager.config"
    assert "max_attempts_per_dimension" in manager.model_fields
    for spec in AGENT_CONFIGS.values():
        agent_root = agents_root / spec.package.replace(".", "/")
        if spec.shared_config is None:
            assert (agent_root / "config.py").is_file()
        else:
            assert not (agent_root / "config.py").exists()


@pytest.mark.parametrize("agent_id", ["architecture_boundary", "responsibility", "dependency_impact", "abstraction", "reuse_opportunity", "component_adaptability"])
def test_existing_investigator_defaults_and_provider_null_semantics_preserved(agent_id):
    config = validate_developer_agent_config(agent_id, {})
    assert (config.max_total_tokens, config.max_context_characters, config.max_model_calls, config.max_tool_calls) == (100_000, 100_000, 16, 24)
    assert config.max_iterations == 3 and config.timeout_seconds == 300
    assert config.provider_rate_limits == ProviderRateLimits(requests_per_minute=14, tokens_per_minute=250_000)
    disabled = validate_developer_agent_config(agent_id, {"provider_rate_limits": {"requests_per_minute": None, "tokens_per_minute": None}})
    assert disabled.provider_rate_limits.requests_per_minute is disabled.provider_rate_limits.tokens_per_minute is None


@pytest.mark.parametrize("agent_id", ["modularity", "reusability"])
def test_coordinator_family_preserves_nested_envelopes_and_has_no_direct_tools(agent_id):
    config = validate_developer_agent_config(agent_id, {})
    assert isinstance(config, CoordinatorConfig) and not config.tools
    assert (config.max_total_tokens, config.max_model_calls, config.max_tool_calls, config.timeout_seconds) == (300_000, 96, 96, 600)
    assert (config.max_rounds, config.max_invocations, config.max_parallel) == (2, 6, 3)
    assert config.invocation_limits.max_total_tokens == 60_000
    assert config.invocation_limits.max_model_calls == InvestigationConfig().max_model_calls
    assert config.invocation_limits.max_tool_calls == 16
    panel = describe_developer_agent_config(agent_id)
    assert panel["hidden_fields"] == ["max_iterations", "tools"]
    assert panel["specific_fields"] == []
    with pytest.raises(ValidationError):
        validate_developer_agent_config(agent_id, {"tools": ["get_source_excerpt"]})


def test_unique_controls_are_not_exposed_as_universal_agent_fields():
    expected = {
        "responsibility": [], "architecture_boundary": [],
        "dependency_impact": ["max_dependency_depth", "max_relationships_per_assessment"],
        "abstraction": ["max_candidates", "max_participants_per_assessment"],
        "reuse_opportunity": ["max_discovery_symbols", "max_feature_characters", "max_groups"],
        "component_adaptability": ["max_components", "max_constraints", "max_scan_characters_per_file", "max_scan_files", "max_signals_per_component"],
        "maintainability_manager": ["max_attempts_per_dimension"],
    }
    for agent_id, fields in expected.items():
        assert describe_developer_agent_config(agent_id)["specific_fields"] == fields
    assert "excerpts" in describe_developer_agent_config("reuse_opportunity")["groups"]
    assert "excerpts" not in describe_developer_agent_config("responsibility")["groups"]
    with pytest.raises(ValidationError):
        validate_developer_agent_config("responsibility", {"max_dependency_depth": 2})


@pytest.mark.parametrize("values", [{"tools": ["execute_code"]},
    {"tools": ["list_files", "list_files"]}, {"prompts": {"invented_node": "text"}}, {"api_key": "not-a-runtime-control"}])
def test_invalid_common_configuration_is_rejected_before_execution(values):
    with pytest.raises(ValidationError):
        validate_developer_agent_config("architecture_boundary", values)


def test_configuration_sources_and_legacy_model_contracts_are_identical():
    from server.config.schemas import ModelSettings as LegacyModelSettings
    from server.runtimes.investigation.schemas import (
        InvestigationConfig as LegacyInvestigationConfig,
    )
    from server.runtimes.investigation.schemas import (
        ProviderRateLimits as LegacyProviderRateLimits,
    )

    assert LegacyInvestigationConfig is InvestigationConfig
    assert LegacyProviderRateLimits is ProviderRateLimits
    assert LegacyModelSettings is ModelSettings
    modularity, reusability = configuration_type("modularity"), configuration_type("reusability")
    assert reusability is modularity is CoordinatorConfig


def test_panel_validated_values_and_prompt_override_drive_the_real_investigator_graph(tmp_path):
    from server.agents.maintainability.modularity.architecture_boundary import (
        ArchitectureBoundaryAgent,
    )

    root = tmp_path / "checkout"
    (root / "domain").mkdir(parents=True)
    (root / "storage").mkdir()
    (root / "domain" / "service.py").write_text("from storage.db import save\n\ndef execute():\n    save()\n", encoding="utf-8")
    (root / "storage" / "db.py").write_text("def save():\n    return None\n", encoding="utf-8")
    config = validate_developer_agent_config("architecture_boundary", {"max_total_tokens": 300_000, "max_tool_calls": 1,
        "prompts": {"plan_investigation": "Configured prompt used by this actual investigation."}})
    model = ScriptedModel([PLAN, call(), evaluation, review()])
    result = asyncio.run(ArchitectureBoundaryAgent(model, config).run(toolset(root), request()))
    assert model.history[0][0].content.startswith(config.prompts["plan_investigation"])
    assert result.tool_calls == 1 and result.findings[0].validation_status == "accepted"


def test_manager_overrides_are_local_and_unknown_agent_does_not_import_arbitrary_modules():
    config = validate_developer_agent_config("maintainability_manager", {"max_attempts_per_dimension": 3})
    assert config.max_total_tokens == 1_000_000 and config.max_model_calls == 300
    assert config.max_attempts_per_dimension == 3 and config.max_parallel == 2
    assert config.prompt_nodes == ("synthesize_assessments",)
    assert config.invocation_limits.max_total_tokens == 300_000
    with pytest.raises(ValidationError):
        validate_developer_agent_config("maintainability_manager", {"prompts": {"synthesize_findings": "wrong node"}})
    with pytest.raises(KeyError):
        configuration_type("server.anything")
