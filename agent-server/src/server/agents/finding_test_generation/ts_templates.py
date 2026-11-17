"""TypeScript/JavaScript test templates for the finding-test generation agent.

These templates cover the few deterministic cases already present in Python, including the
"one top-level class per module" check which is the most direct mechanical rule for SAME-LAYER
SRP violations (e.g. mixing unrelated classes in a single module). Languages in components other
than TypeScript are out of scope; the LLM covers the rest.
"""

import json

from .schemas import VerificationSpec

SUITE_HELPER_TS = r"""// TS helper shared by verification modules.
const fs = require('node:fs');
const path = require('node:path');

export function repoRoot() {
  return path.resolve(process.env.TALLERCITO_REPO_ROOT ?? '.');
}

export function readText(relative: string): string {
  return fs.readFileSync(path.join(repoRoot(), relative), 'utf8');
}

export function classNames(relative: string): string[] {
  const source = readText(relative);
  const stripped = source
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\/\/.*$/gm, "");
  const names: string[] = [];
  const pattern = /(?:^|\n)\s*(?:export\s+(?:default\s+)?)?(?:abstract\s+)?class\s+([A-Za-z_$][A-Za-z0-9_$]*)/g;
  for (const match of stripped.matchAll(pattern)) names.push(match[1]);
  return names;
}
"""


def _header_ts(spec: VerificationSpec) -> str:
    claims = ", ".join(spec.rule_source.document_claim_ids) or "none recorded"
    components = ", ".join(spec.target_components)
    return (
        f"/**\n"
        f" * Verification {spec.verification_id} — {spec.title}.\n"
        f" *\n"
        f" * {spec.property}\n"
        f" *\n"
        f" * Components: {components}\n"
        f" * Documentary claims: {claims}\n"
        f" * Scope: {spec.test_scenario_scope}\n"
        f" */\n"
    )


def _param_scope(spec: VerificationSpec) -> str:
    scope = spec.rule_params.get("scope", spec.source_scope)
    return scope if isinstance(scope, str) and scope else spec.source_scope


def _param_str_list(value) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)) and all(isinstance(item, str) for item in value):
        return list(value)
    return None


def _list_as_ts(value) -> str:
    return json.dumps(value or [], ensure_ascii=False)


def _layer_import_test(spec: VerificationSpec) -> str:
    source_dir = _param_scope(spec)
    forbidden_param = _param_str_list(spec.rule_params.get("forbidden_roots")) or (
        [spec.target_components[1]] if len(spec.target_components) > 1 else []
    )
    allowed = spec.rule_params.get("allowed_exceptions") or []
    forbidden = _list_as_ts(forbidden_param)
    allowed_json = _list_as_ts(allowed if isinstance(allowed, list) else list(allowed))
    return (
        _header_ts(spec)
        + 'import { expect, it } from "vitest";\n'
        + 'import fs from "node:fs";\n'
        + 'import path from "node:path";\n\n'
        + f"const SCOPE = {json.dumps(str(source_dir), ensure_ascii=False)};\n"
        + f"const FORBIDDEN_ROOTS = {forbidden};\n"
        + f"const ALLOWED_EXCEPTIONS = {allowed_json};\n\n"
        + "function walk(directory: string): string[] {\n"
        + "  const root = path.resolve(process.env.TALLERCITO_REPO_ROOT ?? '.');\n"
        + "  const out: string[] = [];\n"
        + "  for (const entry of fs.readdirSync(path.join(root, directory), { withFileTypes: true })) {\n"
        + "    const relative = path.join(directory, entry.name).replace(/\\\\/g, '/');\n"
        + "    if (entry.isDirectory() && entry.name !== 'node_modules' && !entry.name.startsWith('.')) out.push(...walk(relative));\n"
        + "    else if (/\\.(ts|tsx|mts|cts|js|jsx|mjs|cjs)$/.test(entry.name)) out.push(relative);\n"
        + "  }\n"
        + "  return out;\n"
        + "}\n\n"
        + f"it({json.dumps(spec.test_name)}, () => {{\n"
        + "  const modules = walk(SCOPE);\n"
        + "  const offenders: string[] = [];\n"
        + "  for (const relative of modules) {\n"
        + "    const source = fs.readFileSync(path.join(path.resolve(process.env.TALLERCITO_REPO_ROOT ?? '.'), relative), 'utf8');\n"
        + "    const imports = [...source.matchAll(/(?:import|require)\\s*\\(?\\s*['\"{]([^'\"]+)['\"]/g)].map((match) => match[1]);\n"
        + "    for (const specifier of imports) {\n"
        + "      const normalized = specifier.replace(/\\\\/g, '/');\n"
        + "      if (ALLOWED_EXCEPTIONS.some((exception) => normalized.startsWith(exception ?? ''))) continue;\n"
        + "      if (FORBIDDEN_ROOTS.some((root) => normalized.startsWith(root) || normalized === root)) {\n"
        + "        offenders.push(`${relative} imports ${specifier}`);\n"
        + "      }\n"
        + "    }\n"
        + "  }\n"
        + '  expect(offenders, offenders.join("\\n") || "no forbidden imports found").toEqual([]);\n'
        + "});\n"
    )


def _restricted_import_test(spec: VerificationSpec) -> str:
    return _layer_import_test(spec)


def _forbidden_framework_in_layer_test(spec: VerificationSpec) -> str:
    source_dir = _param_scope(spec)
    forbidden_param = _param_str_list(spec.rule_params.get("forbidden_roots")) or (
        [spec.target_components[1]] if len(spec.target_components) > 1 else []
    )
    forbidden = _list_as_ts(forbidden_param)
    return (
        _header_ts(spec)
        + 'import { expect, it } from "vitest";\n'
        + 'import fs from "node:fs";\n'
        + 'import path from "node:path";\n\n'
        + f"const SCOPE = {json.dumps(str(source_dir), ensure_ascii=False)};\n"
        + f"const FORBIDDEN_ROOTS = {forbidden};\n\n"
        + "function walk(directory: string): string[] {\n"
        + "  const root = path.resolve(process.env.TALLERCITO_REPO_ROOT ?? '.');\n"
        + "  const out: string[] = [];\n"
        + "  for (const entry of fs.readdirSync(path.join(root, directory), { withFileTypes: true })) {\n"
        + "    const relative = path.join(directory, entry.name).replace(/\\\\/g, '/');\n"
        + "    if (entry.isDirectory() && entry.name !== 'node_modules' && !entry.name.startsWith('.')) out.push(...walk(relative));\n"
        + "    else if (/\\.(ts|tsx|mts|cts|js|jsx|mjs|cjs)$/.test(entry.name)) out.push(relative);\n"
        + "  }\n"
        + "  return out;\n"
        + "}\n\n"
        + f"it({json.dumps(spec.test_name)}, () => {{\n"
        + "  const offenders: string[] = [];\n"
        + "  for (const relative of walk(SCOPE)) {\n"
        + "    const source = fs.readFileSync(path.join(path.resolve(process.env.TALLERCITO_REPO_ROOT ?? '.'), relative), 'utf8');\n"
        + "    const imports = [...source.matchAll(/(?:import|require)\\s*\\(?\\s*['\"{]([^'\"]+)['\"]/g)].map((match) => match[1]);\n"
        + "    for (const specifier of imports) {\n"
        + "      const normalized = specifier.replace(/\\\\/g, '/');\n"
        + "      if (FORBIDDEN_ROOTS.some((root) => normalized.startsWith(root) || normalized === root)) {\n"
        + "        offenders.push(`${relative} imports ${specifier}`);\n"
        + "      }\n"
        + "    }\n"
        + "  }\n"
        + '  expect(offenders, offenders.join("\\n") || "no forbidden framework imports").toEqual([]);\n'
        + "});\n"
    )


def _private_module_test(spec: VerificationSpec) -> str:
    target = spec.target_components[1] if len(spec.target_components) > 1 else spec.target_components[0]
    owning_package = spec.rule_params.get("owning_package") or target.rsplit("/", 1)[0]
    scope_dir = _param_scope(spec)
    quoted_target = json.dumps(str(target), ensure_ascii=False)
    quoted_owning = json.dumps(str(owning_package), ensure_ascii=False)
    quoted_scope = json.dumps(str(scope_dir), ensure_ascii=False)
    return (
        _header_ts(spec)
        + 'import { expect, it } from "vitest";\n'
        + 'import fs from "node:fs";\n'
        + 'import path from "node:path";\n\n'
        + f"const SCOPE = {quoted_scope};\n"
        + f"const OWNING_PACKAGE = {quoted_owning};\n"
        + f"const PRIVATE_MODULE = {quoted_target};\n\n"
        + "function walk(directory: string): string[] {\n"
        + "  const root = path.resolve(process.env.TALLERCITO_REPO_ROOT ?? '.');\n"
        + "  const out: string[] = [];\n"
        + "  for (const entry of fs.readdirSync(path.join(root, directory), { withFileTypes: true })) {\n"
        + "    const relative = path.join(directory, entry.name).replace(/\\\\/g, '/');\n"
        + "    if (entry.isDirectory() && entry.name !== 'node_modules' && !entry.name.startsWith('.')) out.push(...walk(relative));\n"
        + "    else if (/\\.(ts|tsx|mts|cts|js|jsx|mjs|cjs)$/.test(entry.name)) out.push(relative);\n"
        + "  }\n"
        + "  return out;\n"
        + "}\n\n"
        + f"it({json.dumps(spec.test_name)}, () => {{\n"
        + "  const targets = walk(SCOPE);\n"
        + "  const offenders: string[] = [];\n"
        + "  const owningSegments = OWNING_PACKAGE.split('/');\n"
        + "  for (const relative of targets) {\n"
        + "    if (relative.includes(OWNING_PACKAGE + '/')) continue;\n"
        + "    const source = fs.readFileSync(path.join(path.resolve(process.env.TALLERCITO_REPO_ROOT ?? '.'), relative), 'utf8');\n"
        + "    if (source.includes(PRIVATE_MODULE)) offenders.push(`${relative} imports private module`);\n"
        + "  }\n"
        + '  expect(offenders, offenders.join("\\n") || "no private module imports").toEqual([]);\n'
        + "});\n"
    )


def _one_class_per_module_test(spec: VerificationSpec) -> str:
    target = spec.target_components[0]
    max_classes = spec.rule_params.get("max_classes", 1)
    return (
        _header_ts(spec)
        + 'import { expect, it } from "vitest";\n'
        + 'import fs from "node:fs";\n'
        + 'import path from "node:path";\n\n'
        + f"const TARGET = {json.dumps(str(target), ensure_ascii=False)};\n"
        + f"const MAX_CLASSES = {max_classes};\n\n"
        + f"it({json.dumps(spec.test_name)}, () => {{\n"
        + "  const root = path.resolve(process.env.TALLERCITO_REPO_ROOT ?? '.');\n"
        + "  const source = fs.readFileSync(path.join(root, TARGET), 'utf8');\n"
        + "  const names = (source.match(/(?:^|\\n)\\s*(?:export\\s+(?:default\\s+)?)?(?:abstract\\s+)?class\\s+[A-Za-z_$][A-Za-z0-9_$]*/g) ?? []);\n"
        + "  expect(names.length, `${TARGET} must define at most ${MAX_CLASSES} top-level class(es); found ${names.length}`).toBeLessThanOrEqual(MAX_CLASSES);\n"
        + "});\n"
    )


def _no_environ_in_scope_test(spec: VerificationSpec) -> str:
    source_dir = _param_scope(spec)
    return (
        _header_ts(spec)
        + 'import { expect, it } from "vitest";\n'
        + 'import fs from "node:fs";\n'
        + 'import path from "node:path";\n\n'
        + f"const SCOPE = {json.dumps(str(source_dir), ensure_ascii=False)};\n\n"
        + "function walk(directory: string): string[] {\n"
        + "  const root = path.resolve(process.env.TALLERCITO_REPO_ROOT ?? '.');\n"
        + "  const out: string[] = [];\n"
        + "  for (const entry of fs.readdirSync(path.join(root, directory), { withFileTypes: true })) {\n"
        + "    const relative = path.join(directory, entry.name).replace(/\\\\/g, '/');\n"
        + "    if (entry.isDirectory() && entry.name !== 'node_modules' && !entry.name.startsWith('.')) out.push(...walk(relative));\n"
        + "    else if (/\\.(ts|tsx|mts|cts|js|jsx|mjs|cjs)$/.test(entry.name)) out.push(relative);\n"
        + "  }\n"
        + "  return out;\n"
        + "}\n\n"
        + f"it({json.dumps(spec.test_name)}, () => {{\n"
        + "  const offenders: string[] = [];\n"
        + "  for (const relative of walk(SCOPE)) {\n"
        + "    const source = fs.readFileSync(path.join(path.resolve(process.env.TALLERCITO_REPO_ROOT ?? '.'), relative), 'utf8');\n"
        + "    if (/process\\s*\\.\\s*env(?:\\s*\\.|\\s*\\[)/.test(source)) offenders.push(relative);\n"
        + "  }\n"
        + '  expect(offenders, offenders.join("\\n") || "no process.env reads in scope").toEqual([]);\n'
        + "});\n"
    )


def _circular_import_test(spec: VerificationSpec) -> str:
    source_dir = _param_scope(spec)
    quoted = json.dumps(str(source_dir), ensure_ascii=False)
    return (
        _header_ts(spec)
        + 'import { expect, it } from "vitest";\n'
        + 'import fs from "node:fs";\n'
        + 'import path from "node:path";\n\n'
        + f"it({json.dumps(spec.test_name)}, () => {{\n"
        + f"  const root = path.resolve(process.env.TALLERCITO_REPO_ROOT ?? '.');\n"
        + f"  const entries = fs.readdirSync(path.join(root, {quoted}), {{ withFileTypes: true }});\n"
        + "  const target = entries.filter((entry) => /\\.(ts|tsx|mts|js|jsx|mjs|cjs)$/.test(entry.name)).map((entry) => entry.name);\n"
        + "  expect(target.length, 'Scope must contain TypeScript/JavaScript sources to analyze').toBeGreaterThanOrEqual(0);\n"
        + "});\n"
    )


def _forbidden_call_test(spec: VerificationSpec) -> str:
    params = spec.rule_params or {}
    forbidden = _list_as_ts(params.get("forbidden_collaborators") or [])
    return (
        _header_ts(spec)
        + 'import { expect, it } from "vitest";\n\n'
        + f"const FORBIDDEN = {forbidden};\n\n"
        + f"it({json.dumps(spec.test_name)}, () => {{\n"
        + "  expect(FORBIDDEN.length, 'forbidden_call TS template requires forbidden_collaborators in rule_params').toBeGreaterThan(0);\n"
        + "});\n"
    )


def _contract_states_test(spec: VerificationSpec) -> str:
    target = spec.target_components[0]
    quoted_target = json.dumps(str(target), ensure_ascii=False)
    return (
        _header_ts(spec)
        + 'import { expect, it } from "vitest";\n'
        + 'import fs from "node:fs";\n'
        + 'import path from "node:path";\n\n'
        + f"const TARGET = {quoted_target};\n"
        + f"const MAX_CLASSES = {spec.rule_params.get('max_classes', 1)};\n\n"
        + f"it({json.dumps(spec.test_name)}, () => {{\n"
        + "  const root = path.resolve(process.env.TALLERCITO_REPO_ROOT ?? '.');\n"
        + "  const source = fs.readFileSync(path.join(root, TARGET), 'utf8');\n"
        + "  const names = (source.match(/(?:^|\\n)\\s*(?:export\\s+(?:default\\s+)?)?(?:abstract\\s+)?class\\s+[A-Za-z_$][A-Za-z0-9_$]*/g) ?? []);\n"
        + "  expect(names.length, `${TARGET} must define at most ${MAX_CLASSES} top-level class(es); found ${names.length}`).toBeLessThanOrEqual(MAX_CLASSES);\n"
        + "});\n"
    )


def _contract_states_dynamic_test(spec: VerificationSpec) -> str:
    return _contract_states_test(spec)


_RENDERERS_TS = {
    "layer_import": _layer_import_test,
    "restricted_import": _restricted_import_test,
    "forbidden_framework_in_layer": _forbidden_framework_in_layer_test,
    "private_module_access": _private_module_test,
    "one_class_per_module": _one_class_per_module_test,
    "no_environ_in_scope": _no_environ_in_scope_test,
    "circular_import": _circular_import_test,
    "forbidden_call": _forbidden_call_test,
    "contract_states": _contract_states_test,
    "contract_states_dynamic": _contract_states_dynamic_test,
}


def render_ts_test_file(spec: VerificationSpec) -> tuple[str, str]:
    renderer = _RENDERERS_TS.get(spec.rule_kind or "")
    if renderer is None:
        raise ValueError(f"No TS rule renderer for {spec.rule_kind!r} (verification {spec.verification_id}).")
    return spec.test_path, renderer(spec)


def render_ts_helper() -> tuple[str, str]:
    return "tests/helper.ts", SUITE_HELPER_TS
