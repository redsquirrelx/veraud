"""Reusable, parameterized verification rules for architecture boundary checks.

Every rule here is a self-contained predicate over the AST plus a renderer for
an equivalent pytest test. The pipeline renders rule tests deterministically;
the LLM is used to *choose* a rule and *fill* its parameters, never to
re-implement a parser ad hoc.
"""

from collections.abc import Callable
from dataclasses import dataclass

from server.runtimes.verification.tools.package_discovery import dotted_module

from .schemas import VerificationSpec
from .test_templates import (
    _circular_import_test,
    _collaborator_call_test,
    _contract_states_dynamic_test,
    _contract_states_test,
    _layer_import_test,
    _no_environ_test,
    _one_class_per_module_test,
    _private_attribute_test,
    _private_module_test,
    _restricted_import_test,
)


@dataclass(frozen=True)
class Rule:
    rule_id: str
    label: str
    description: str
    matcher: Callable[[VerificationSpec], bool]
    renderer: Callable[[VerificationSpec], str]


def _boundary_import(spec: VerificationSpec) -> bool:
    return spec.rule_kind in {"layer_import", "forbidden_framework_in_layer", "restricted_import"}


def _component_prefix_private(spec: VerificationSpec) -> bool:
    if len(spec.target_components) < 2:
        return False
    candidate = dotted_module(spec.target_components[1])
    return candidate.rsplit(".", 1)[-1].startswith("_")


def _private_module(spec: VerificationSpec) -> bool:
    return spec.rule_kind == "private_module_access" or _component_prefix_private(spec)


def _contract_states(spec: VerificationSpec) -> bool:
    return spec.rule_kind in {"contract_states", "contract_states_dynamic", "forbidden_call"}


def _contract_states_dynamic(spec: VerificationSpec) -> bool:
    return spec.rule_kind in {"contract_states", "contract_states_dynamic", "forbidden_call"}


def _restricted_import(spec: VerificationSpec) -> bool:
    return spec.rule_kind in {"layer_import", "forbidden_framework_in_layer", "restricted_import"}


def _private_attribute(spec: VerificationSpec) -> bool:
    return spec.rule_kind == "private_attribute_access"


def _forbidden_call(spec: VerificationSpec) -> bool:
    # Single-responsibility obligations may be re-implemented by the LLM as a
    # collaborator-call assertion when a "must not call X" clause is present.
    return spec.rule_kind in {"contract_states", "contract_states_dynamic", "forbidden_call", "one_class_per_module"}


def _one_class_per_module(spec: VerificationSpec) -> bool:
    return spec.rule_kind in {"contract_states", "contract_states_dynamic", "forbidden_call", "one_class_per_module"}


def _no_environ(spec: VerificationSpec) -> bool:
    return spec.rule_kind == "no_environ_in_scope"


def _circular_import(spec: VerificationSpec) -> bool:
    return spec.rule_kind == "circular_import"


RULES: dict[str, Rule] = {
    "layer_import": Rule("layer_import", "Forbidden layer import",
        "Files under scope must not import modules beneath the target components.",
        _boundary_import, _layer_import_test),
    "forbidden_framework_in_layer": Rule("forbidden_framework_in_layer", "Forbidden framework import",
        "Files under scope must not import named framework packages.",
        _boundary_import, _layer_import_test),
    "restricted_import": Rule("restricted_import", "Restricted import (allowlist)",
        "Files under scope may only import modules beneath the allowlisted roots.",
        _restricted_import, _restricted_import_test),
    "private_module_access": Rule("private_module_access", "Private module access",
        "Modules named _x may not be imported outside their owning package.",
        _private_module, _private_module_test),
    "private_attribute_access": Rule("private_attribute_access", "Private attribute access",
        "Underscored attributes must not be touched from outside the owning package.",
        _private_attribute, _private_attribute_test),
    "contract_states": Rule("contract_states", "Contract-state vocabularies",
        "Variants of a contract must return from a shared vocabulary of literal states.",
        _contract_states, _contract_states_test),
    "contract_states_dynamic": Rule("contract_states_dynamic", "Dynamic contract verification",
        "Executes the real implementation with synthesized inputs and mocked constructor collaborators: "
        "shared-vocabulary contract plus call-observation of forbidden collaborators.",
        _contract_states_dynamic, _contract_states_dynamic_test),
    "no_environ_in_scope": Rule("no_environ_in_scope", "No environment reads",
        "Files under scope may not read os.environ / os.getenv; config must inject via composition root.",
        _no_environ, _no_environ_test),
    "circular_import": Rule("circular_import", "No circular imports",
        "No pair of modules within scope may import each other.",
        _circular_import, _circular_import_test),
    "forbidden_call": Rule("forbidden_call", "Forbidden collaborator call",
        "A specific method must not invoke a named collaborator (e.g. inside .quote, no audit sink append).",
        _forbidden_call, _collaborator_call_test),
    "one_class_per_module": Rule("one_class_per_module", "One resource per storage module",
        "A storage adapter module must only define one public class to avoid responsibility overlap at file level.",
        _one_class_per_module, _one_class_per_module_test),
}


def rule_ids() -> list[str]:
    return list(RULES)


def applicable_rules(spec: VerificationSpec) -> list[Rule]:
    return [rule for rule in RULES.values() if rule.matcher(spec)]
