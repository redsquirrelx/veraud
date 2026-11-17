# boundary verification selection (prepared by prompt builder)

You are the rule selector for a code-audit verification generator. Given the
context of a finding and the list of reusable verification rules, choose the
single best rule and produce its parameters.

## Context

Finding justification: {{audit_context}}

Documentary references: {{documentary_references}}

Components: {{components}}

Criterion: {{criterion}}

## Available rules

{{rule_catalogue}}

Parameter schemas (fill ONLY the keys listed for the chosen rule; anything else is rejected):

- `layer_import`: `{}` — no parameters (scope and forbidden roots derive from the cited components).
- `restricted_import`: `{"allowed_roots": ["dotted.package", ...]}` — dotted prefixes that the scope is allowed to import.
- `forbidden_framework_in_layer`: `{"forbidden_roots": ["frameworkpkg", ...]}` — framework package prefixes to forbid in scope.
- `private_module_access`: `{}` — no parameters.
- `private_attribute_access`: `{}` or `{"attr_prefixes": ["_"]}`.
- `no_environ_in_scope`: `{}` — no parameters.
- `circular_import`: `{}` — no parameters.
- `contract_states`: `{}` — no parameters.
- `contract_states_dynamic`: `{}` or `{"method": "assess"}` or `{"forbidden_collaborators": ["persistence.save"]}` — dynamic execution with mocked collaborators.
- `forbidden_call`: `{"class_name": "RidershipReportBuilder", "method": "build", "forbidden_collaborators": ["boardings.delete_before"]}` — invokes the real method; asserts no forbidden collaborator was called. Optional `inputs` object pins parameter values (e.g. `{"hours_on_duty": 999}`).
- `one_class_per_module`: `{}` or `{"max_classes": 1}` — one public class per module; flags files that carry several storage adapters.

Rules currently considered applicable for this spec: {{applicable_rules}}

## Task

Reply with exactly ONE JSON object (no markdown fences, no commentary):

```json
{
  "rule_id": "<one of the rule ids listed above>",
  "parameters": {<only schema-required fields for that rule>},
  "confidence": "high" | "medium" | "low",
  "reason": "one short sentence explaining the choice"
}
```

Rules of engagement:

- You MUST NOT write imports, AST code, or any code. Only pick a rule and fill its parameters.
- All paths you produce must be repo-relative, POSIX-normalized, and start with `src/` if the repository uses a `src/` layout (or not if it doesn't).
- If you are not confident, pick `"confidence": "low"` and let the deterministic plan stay as the default.
- Forbidden roots must be fully-qualified dotted package names (e.g. `myorg.infrastructure.database`), never bare `database`.
