"""Deterministic derivation of VerificationSpecs from an audit export.

Only rules with explicit support in the finding data are produced. Findings
without an applicable deterministic rule yield no spec and an explicit
``not_verifiable`` limitation â€” this module never invents requirements that
the audit did not document.
"""

import re
from pathlib import PurePosixPath

from server.runtimes.verification.templates.node_runtime import JS_SUFFIXES
from server.runtimes.verification.tools.package_discovery import (
    dotted_module,
    import_root,
    module_parts,
)

from .schemas import AuditDocument, Finding, RuleSource, VerificationSpec


def _language_of(components) -> str:
    if not components:
        return "python"
    suffixes = {PurePosixPath(c).suffix.lower() for c in components}
    if suffixes & {".ts", ".tsx", ".mts", ".cts"}:
        return "typescript"
    if suffixes & JS_SUFFIXES:
        return "javascript"
    return "python"


def _with_language(specs: list[VerificationSpec]) -> list[VerificationSpec]:
    annotated: list[VerificationSpec] = []
    for spec in specs:
        language = _language_of(spec.target_components)
        update: dict = {"language": language}
        if language != "python":
            path = spec.test_path
            for candidate in (".py", ".py"):
                if path.endswith(candidate):
                    path = path[: -len(candidate)] + ".test.tsx"
                    break
            update["test_path"] = path
        annotated.append(spec.model_copy(update=update))
    return annotated


def _layer_name(component: str) -> str | None:
    parts = module_parts(component)
    if len(parts) >= 3:
        return parts[1]
    return None


def _slug(text: str, maximum: int = 48) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug[:maximum].strip("_") or "verification"


def _document_claims(finding: Finding) -> list[str]:
    return list(dict.fromkeys(finding.technical_details.document_claim_ids))


def _documentary_summary(finding: Finding) -> str:
    statements = [reference.statement for reference in finding.technical_details.documentary_references if reference.statement]
    return " | ".join(dict.fromkeys(statements)) or finding.justification


def _documentary_limits(finding: Finding, *, extra: list[str] | None = None) -> list[str]:
    limits = [
        "The test demonstrates the declared condition only within the declared scope; it does not certify the architecture globally.",
        "The original verification_status of the finding is preserved and is not changed by this test.",
    ]
    for reference in finding.technical_details.documentary_references:
        if reference.commit:
            limits.append(f"Documentary reference {reference.document_claim_id} is pinned to commit {reference.commit}.")
    if extra:
        limits.extend(extra)
    return limits


def _layer_root(component: str) -> str:
    """Directory of the offending layer (e.g. src/urbanmesh/application)."""

    parts = component.replace("\\", "/").split("/")
    if "src" in parts:
        index = parts.index("src")
        if len(parts) > index + 2:
            return "/".join(parts[: index + 3])
    if len(parts) >= 2:
        return "/".join(parts[:2])
    return component.rsplit("/", 1)[0]


def _boundary_spec(finding: Finding, verification_id: str) -> VerificationSpec:
    source_component, forbidden_component = finding.components[:2]
    source_layer = _layer_name(source_component)
    private_module = PurePosixPath(forbidden_component).stem.startswith("_")
    forbidden_root = import_root(forbidden_component) or dotted_module(forbidden_component) or forbidden_component

    property_text = _documentary_summary(finding)
    if private_module:
        violation = (f"Code outside the package containing {forbidden_component} imports the private module "
                     f"'{dotted_module(forbidden_component)}' (e.g. reads or mutates its internals).")
        fixed = "No module outside the owning package imports the private module; access goes through the public API."
        scope = source_component
        scenario_scope = "All Python files in the repository outside the owning package of the private module."
        limits = ["AST analysis does not detect dynamic imports (importlib) or attribute access without an import statement."]
    else:
        violation = (f"A module under the layer scope '{_layer_root(source_component)}' imports "
                     f"'{forbidden_root}' ({source_layer or 'unknown'} layer).")
        fixed = f"No module in scope imports '{forbidden_root}' or any module beneath it."
        scope = _layer_root(source_component)
        scenario_scope = f"All Python files under {scope}; the layer is scanned, not only the cited file."
        limits = [
            "AST analysis does not detect dynamic imports (importlib) or conditional imports built at runtime.",
            "The documented exception for the composition root (bootstrap.py) is honoured within this scope.",
        ]

    return VerificationSpec(
        finding_id=finding.id,
        verification_id=verification_id,
        title=finding.title,
        rule_source=RuleSource(
            document_claim_ids=_document_claims(finding),
            evidence_ids=[*finding.evidence_ids, *finding.technical_details.evidence_ids],
        ),
        target_components=list(finding.components),
        property=property_text,
        strategy="static_ast",
        scenarios=[violation],
        violation_oracle=violation,
        fixed_oracle=fixed,
        limits=_documentary_limits(finding, extra=limits),
        source_scope=scope,
        test_scenario_scope=scenario_scope,
        test_path=f"tests/test_{_slug(finding.title)}.py",
        test_name=f"test_{_slug(finding.title)}",
        rule_kind="private_module_access" if private_module else "layer_import",
    )


def _contract_spec(finding: Finding, verification_id: str) -> VerificationSpec:
    component = finding.components[0]
    statement = _documentary_summary(finding)
    return VerificationSpec(
        finding_id=finding.id,
        verification_id=verification_id,
        title=finding.title,
        rule_source=RuleSource(
            document_claim_ids=_document_claims(finding),
            evidence_ids=[*finding.evidence_ids, *finding.technical_details.evidence_ids],
        ),
        target_components=list(finding.components),
        property=statement,
        strategy="static_ast",
        scenarios=[
            "Static analysis of the component module: every public class exposing `assess` contributes its returned string-literal vocabulary; no runtime behaviour is exercised.",
        ],
        violation_oracle=(
            "At least two assess-like variant implementations in the module return disjoint literal string vocabularies."
        ),
        fixed_oracle="All assess-like variant implementations share at least one literal state value.",
        limits=_documentary_limits(finding, extra=[
            "Only string-literal return expressions are compared; computed or aliased states are invisible to this check.",
            "State compatibility does not demonstrate single responsibility, modularity or cohesion.",
            "The finding is 'inconclusive' and 'insufficient_evidence' in the audit export; this test probes only the declared state contract.",
            "If no string literals are returned by any variant, the verification is reported NOT_VERIFIABLE instead of guessing.",
        ]),
        source_scope=component,
        test_scenario_scope=(
            f"Static analysis of {component} for all classes exposing a public assess method."
        ),
        test_path=f"tests/test_{_slug(finding.title)}.py",
        test_name=f"test_{_slug(finding.title)}",
        rule_kind="contract_states",
    )


def _contract_dynamic_spec(finding: Finding, verification_id: str) -> VerificationSpec:
    component = finding.components[0]
    statement = _documentary_summary(finding)
    return VerificationSpec(
        finding_id=finding.id,
        verification_id=verification_id,
        title=f"{finding.title} (dynamic)",
        rule_source=RuleSource(
            document_claim_ids=_document_claims(finding),
            evidence_ids=[*finding.evidence_ids, *finding.technical_details.evidence_ids],
        ),
        target_components=list(finding.components),
        property=statement,
        strategy="dynamic_mock",
        scenarios=[
            "Dynamic execution: invoke the real implementations of every variant with a synthesized input; constructor collaborators are mocked by parameter name.",
            "A variant whose call path raises for a configuration reason is NOT_VERIFIABLE, never a violation.",
        ],
        violation_oracle=(
            "The real implementations produce disjoint literal return vocabularies, or a configured "
            "forbidden collaborator (rule_params.forbidden_collaborators) is invoked."
        ),
        fixed_oracle="All assess-like variants share at least one literal state value and forbidden collaborators are never invoked.",
        limits=_documentary_limits(finding, extra=[
            "Dynamic execution uses one synthesized input; behavior on other inputs is unverified.",
            "If the module cannot be imported or the input cannot be synthesized for a configuration reason, the result is EXECUTION_ERROR, never VIOLATION_PRESENT.",
            "State sharing does not demonstrate single responsibility, modularity or cohesion.",
            "The finding is 'inconclusive' in the audit export; this test probes only the declared state contract.",
        ]),
        source_scope=component,
        test_scenario_scope=(
            f"Dynamic execution of {component} for all classes exposing a public assess method."
        ),
        test_path=f"tests/test_{_slug(finding.title)}_dynamic.py",
        test_name=f"test_{_slug(finding.title)}_dynamic",
        rule_kind="contract_states_dynamic",
        rule_params={},
    )


def _llm_spec(finding: Finding, verification_id: str, language: str) -> VerificationSpec:
    statement = _documentary_summary(finding)
    suffix = ".test.tsx" if language in ("typescript", "javascript") else ".py"
    test_path = f"tests/test_{_slug(finding.title)}{suffix}"
    test_name = f"test_{_slug(finding.title)}"
    spec = VerificationSpec(
        finding_id=finding.id,
        verification_id=verification_id,
        title=finding.title,
        rule_source=RuleSource(
            document_claim_ids=_document_claims(finding),
            evidence_ids=[*finding.evidence_ids, *finding.technical_details.evidence_ids],
        ),
        target_components=list(finding.components),
        property=statement,
        strategy="static_ast",
        scenarios=[statement],
        violation_oracle="The check fails when the described property does not hold.",
        fixed_oracle="The check passes when the described property holds.",
        limits=_documentary_limits(finding, extra=[
            "The LLM-authored test may be underconstrained; verify the assertion matches the finding before relying on it.",
            "Without a green control, a passing test indicates only that absence of the property could not be demonstrated in scope.",
        ]),
        source_scope=finding.components[0] if finding.components else ".",
        test_scenario_scope=f"Focused check of the described component(s): {', '.join(finding.components)}",
        test_path=test_path,
        test_name=test_name,
        rule_kind=None,
    )
    spec.language = language
    return spec


def _language_from_components(components: list[str]) -> str:
    if not components:
        return "python"
    suffixes = {PurePosixPath(component).suffix.lower() for component in components if component}
    if suffixes & {".ts", ".tsx", ".mts", ".cts"}:
        return "typescript"
    if suffixes & {".js", ".jsx", ".mjs", ".cjs"}:
        return "javascript"
    return "python"


def plan_verifications(document: AuditDocument, *, llm=None) -> tuple[list[VerificationSpec], list[str]]:
    """Derive verification specs from the audit; LLM free-form fallback for findings without a deterministic rule."""

    specs: list[VerificationSpec] = []
    limitations: list[str] = []
    verification_counter = 0
    for finding in document.findings:
        criterion = finding.criterion.id

        def _next_id() -> str:
            nonlocal verification_counter
            verification_counter += 1
            return f"verification-{verification_counter:03d}"

        if criterion == "architectural-boundaries" and len(finding.components) >= 2:
            specs.append(_boundary_spec(finding, _next_id()))
        elif criterion == "single-responsibility" and finding.components:
            specs.append(_contract_spec(finding, _next_id()))
            specs.append(_contract_dynamic_spec(finding, _next_id()))
        else:
            language = _language_from_components(list(finding.components))
            llm_spec = _llm_spec(finding, _next_id(), language)
            if llm is not None:
                specs.append(llm_spec)
                limitations.append(
                    f"finding {finding.id}: no deterministic verification rule applies "
                    f"(criterion={criterion!r}, components={len(finding.components)}); LLM will attempt a {language} verification."
                )
            else:
                limitations.append(
                    f"finding {finding.id}: no deterministic verification rule applies "
                    f"(criterion={criterion!r}, components={len(finding.components)}); marked NOT_VERIFIABLE until LLM generation is available."
                )
    specs: list[VerificationSpec] = _with_language(specs)
    return specs, limitations
