"""Select which rule applies to a spec and fill its parameters.

The LLM is an arbiter, never the author: it picks a rule id from the catalogue
produced by the deterministic matcher (``rules.applicable_rules``) and fills a
few parameters. The deterministic renderer still emits the test, so a rejected
selection degrades gracefully to the deterministic plan.

A selection is applied to the spec only when the LLM answer parses as JSON,
names a rule from the allowed catalogue, and passes the per-rule parameter
validation. ``low`` confidence never overrides the deterministic plan.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from .rules import RULES, applicable_rules
from .schemas import AuditDocument, Finding, VerificationSpec

PROMPT_PATH = Path(__file__).parent / "prompts" / "boundary_verification.md"
PROMPT = PROMPT_PATH.read_text(encoding="utf-8")

RULE_INVOCATION = {
    "layer_import": "layer_import(scope, forbidden_roots, allowed_exceptions)",
    "restricted_import": "restricted_import_check(scope, allowed_roots)",
    "forbidden_framework_in_layer": "forbidden_framework_in_layer(scope, forbidden_roots)",
    "private_module_access": "find_private_module_imports(private_module, owning_package)",
    "private_attribute_access": "forbidden_attribute_check(scope, module_prefix, attr_prefixes)",
    "no_environ_in_scope": "no_environ_in_scope(scope)",
    "circular_import": "circular_import_check(scope)",
    "contract_states_dynamic": "dynamic contract verification (synthesized inputs + mocked collaborators)",
    "forbidden_call": "collaborator invocation check (synthesized inputs + mocked collaborators; assert forbidden collaborator is never called)",
    "one_class_per_module": "one public class per module (storage adapters must hold exactly one resource)",
}

_PLACEHOLDER = re.compile(r"\{\{([a-z_]+)\}\}")
_DOTTED = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")

# Per-rule parameter schemas. The LLM may only fill these keys; anything else
# is rejected and the deterministic plan stays in charge. Scope narrowing is
# deliberately not an LLM-fillable parameter: the deterministic plan controls
# the verified surface so the audit cannot be silently weakened.
_RULE_PARAMETER_KEYS = {
    "layer_import": frozenset(),
    "restricted_import": frozenset({"allowed_roots"}),
    "forbidden_framework_in_layer": frozenset({"forbidden_roots"}),
    "private_module_access": frozenset(),
    "private_attribute_access": frozenset({"attr_prefixes"}),
    "no_environ_in_scope": frozenset(),
    "circular_import": frozenset(),
    "contract_states": frozenset(),
    "contract_states_dynamic": frozenset({"forbidden_collaborators", "method"}),
    "forbidden_call": frozenset({"class_name", "method", "forbidden_collaborators", "inputs"}),
    "one_class_per_module": frozenset({"max_classes"}),
}


class SelectionParameters(BaseModel):
    """Permissive parameter bag; unknown keys are kept for the manifest."""

    model_config = {"extra": "allow"}


class LLMSelectionResponse(BaseModel):
    rule_id: str
    parameters: dict[str, object] = Field(default_factory=dict)
    confidence: str = "low"
    reason: str = ""


@dataclass(frozen=True)
class SelectionResult:
    rule_id: str | None
    parameters: dict[str, object] = field(default_factory=dict)
    confidence: str = "low"
    reason: str = ""
    applied: bool = False
    note: str = ""
    applied_spec: VerificationSpec | None = None
    reportable: bool = True  # False for expected deterministic fall-backs (low confidence, no capability)


def _catalogue_text(rule_ids: list[str]) -> str:
    lines = []
    for rid in rule_ids:
        rule = RULES.get(rid)
        if rule is None:
            continue
        lines.append(f"- `{rule.rule_id}` — {rule.label}: {rule.description} [call: {RULE_INVOCATION.get(rid, rid)}]")
    return "\n".join(lines)


def _finding_references(finding: Finding) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for reference in finding.technical_details.documentary_references:
        refs.append({
            "id": reference.document_claim_id,
            "subject": reference.subject,
            "statement": reference.statement,
            "constraint": reference.constraint,
        })
    return refs


def build_selection_prompt(spec: VerificationSpec, document: AuditDocument, finding: Finding,
                           allowed_rule_ids: list[str]) -> str:
    allowed = [rid for rid in dict.fromkeys(allowed_rule_ids) if rid in RULES]
    values = {
        "audit_context": finding.justification or finding.description or "",
        "documentary_references": json.dumps(_finding_references(finding), ensure_ascii=False),
        "components": ", ".join(dict.fromkeys(finding.components or spec.target_components)),
        "criterion": f"{finding.criterion.id} · {finding.quality_attribute}/{finding.subcharacteristic}".strip(" ·"),
        "rule_catalogue": _catalogue_text(list(RULES)),
        "applicable_rules": ", ".join(allowed) if allowed else "none; declare low confidence",
    }

    def _substitute(match: re.Match[str]) -> str:
        return str(values.get(match.group(1), ""))

    return _PLACEHOLDER.sub(_substitute, PROMPT)


def _validate_dotted_list(value, name: str) -> str | None:
    if not isinstance(value, list) or not value:
        return f"{name} must be a non-empty list of dotted module prefixes"
    for item in value:
        if not isinstance(item, str) or not _DOTTED.match(item):
            return f"{name} entry {item!r} is not a dotted module prefix"
    return None


def _validate_parameters(rule_id: str, parameters: dict[str, object]) -> str | None:
    allowed_keys = _RULE_PARAMETER_KEYS.get(rule_id)
    if allowed_keys is None:
        return f"no parameter schema for rule {rule_id!r}"
    unknown = sorted(set(parameters) - allowed_keys)
    if unknown:
        return f"{rule_id} does not accept parameters {unknown}; the deterministic plan keeps the rest"
    if rule_id == "restricted_import":
        return _validate_dotted_list(parameters.get("allowed_roots"), "allowed_roots")
    if rule_id == "forbidden_framework_in_layer":
        return _validate_dotted_list(parameters.get("forbidden_roots"), "forbidden_roots")
    if rule_id == "private_attribute_access":
        prefixes = parameters.get("attr_prefixes")
        if prefixes is not None and (
            not isinstance(prefixes, list) or not prefixes
            or not all(isinstance(item, str) and item for item in prefixes)
        ):
            return "attr_prefixes must be a non-empty list of string prefixes"
    if rule_id == "contract_states_dynamic":
        collaborators = parameters.get("forbidden_collaborators")
        if collaborators is not None and (
            not isinstance(collaborators, list)
            or not all(isinstance(item, str) and item for item in collaborators)
        ):
            return "forbidden_collaborators must be a list of dotted attribute paths (e.g. persistence.save)"
        method = parameters.get("method")
        if method is not None and (not isinstance(method, str) or not method.isidentifier()):
            return "method must be a valid Python identifier"
    if rule_id == "forbidden_call":
        class_name = parameters.get("class_name")
        if not isinstance(class_name, str) or not class_name.isidentifier():
            return "class_name must be a valid Python identifier"
        method = parameters.get("method")
        if not isinstance(method, str) or not method.isidentifier():
            return "method must be a valid Python identifier"
        collaborators = parameters.get("forbidden_collaborators")
        if not isinstance(collaborators, list) or not collaborators \
                or not all(isinstance(item, str) and item.strip() for item in collaborators):
            return "forbidden_collaborators must be a non-empty list of dotted attribute paths (e.g. audit_sink.append)"
        dotted = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")
        for item in collaborators:
            if not dotted.match(item):
                return f"forbidden_collaborators entry {item!r} is not a dotted attribute path"
        inputs = parameters.get("inputs")
        if inputs is not None and not isinstance(inputs, dict):
            return "inputs must be a JSON object of parameter names to literal values"
    if rule_id == "one_class_per_module":
        max_classes = parameters.get("max_classes", 1)
        if not isinstance(max_classes, int) or max_classes < 1:
            return "max_classes must be a positive integer"
    return None


def parse_selection(raw: str, allowed_rule_ids: list[str]) -> tuple[LLMSelectionResponse | None, str | None]:
    text = raw.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None, "response contained no JSON object"
    try:
        response = LLMSelectionResponse.model_validate(json.loads(match.group(0)))
    except (json.JSONDecodeError, ValidationError) as error:
        return None, f"response did not match the selection schema ({error})"
    if response.rule_id not in allowed_rule_ids:
        return None, f"rule_id {response.rule_id!r} is not one of the allowed rules ({', '.join(allowed_rule_ids)})"
    if not isinstance(response.parameters, dict):
        return None, "parameters must be a JSON object"
    problem = _validate_parameters(response.rule_id, response.parameters)
    if problem:
        return None, problem
    return response, None


def apply_selection(spec: VerificationSpec, response: LLMSelectionResponse) -> VerificationSpec:
    parameters = dict(spec.rule_params)
    parameters.update(response.parameters)
    return spec.model_copy(update={"rule_kind": response.rule_id, "rule_params": parameters})


async def select_boundary_verification(spec: VerificationSpec, document: AuditDocument, finding: Finding,
                                       llm_client) -> SelectionResult:
    """Ask the LLM for a rule choice; a rejected answer leaves the spec untouched."""
    allowed = [rule.rule_id for rule in applicable_rules(spec)]
    if not allowed:
        return SelectionResult(rule_id=None, reason="no applicable rules",
                               note="deterministic plan kept (no applicable rule candidates)", reportable=False)
    select_method = getattr(llm_client, "select_rule", None)
    if select_method is None:
        return SelectionResult(rule_id=None, reason="client exposes no selection capability",
                               note="deterministic plan kept (LLM selection not supported)", reportable=False)
    prompt = build_selection_prompt(spec, document, finding, allowed)
    try:
        raw = await select_method(prompt)
    except Exception as error:  # noqa: BLE001 - tool boundary; fall back to the deterministic plan
        return SelectionResult(rule_id=None, reason=f"selection call failed: {error}",
                               note=f"deterministic plan kept (selection error: {type(error).__name__})")
    response, problem = parse_selection(str(raw), allowed)
    if response is None:
        return SelectionResult(rule_id=None, reason=problem or "invalid selection",
                               note=f"deterministic plan kept ({problem or 'invalid selection'})")
    if response.confidence == "low":
        return SelectionResult(rule_id=response.rule_id, parameters=response.parameters,
                               confidence="low", reason=response.reason,
                               note=f"deterministic plan kept (LLM answered low confidence: {response.reason or 'no reason given'})",
                               reportable=False)
    applied = apply_selection(spec, response)
    return SelectionResult(rule_id=response.rule_id, parameters=applied.rule_params,
                           confidence=response.confidence, reason=response.reason, applied=True,
                           applied_spec=applied,
                           note=f"LLM selected `{response.rule_id}` ({response.confidence}): {response.reason or 'no reason given'}")
