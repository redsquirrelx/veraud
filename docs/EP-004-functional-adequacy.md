# EP-004 — Functional Adequacy

## Overview

The Functional Adequacy module evaluates software requirements against source-code evidence and produces structured, traceable findings.

The module is part of VERAUD's shared multi-agent architecture. It is not a standalone auditing system.

## Architecture

The `functional_adequacy` agent is registered through `AgentExecutionService` and exposed through the `functional-adequacy` pipeline using `GenericPipelineService`.

The agent uses semantic retrieval with `sentence-transformers/all-MiniLM-L6-v2` to rank candidate code fragments. A language model then evaluates the retrieved evidence and generates a classification with supporting justification.

The `repository_adapter.py` component reuses the shared `RepositoryAnalysisService` to transform source files from a local repository into the agent's existing input contract.

The repository adapter is a supporting component, not an additional agent.

Semantic similarity alone does not establish functional compliance.

## Input Contract

The agent accepts a JSON object containing:

- `requirements`: objects with `requirement_id` and `description`.
- `code_fragments`: objects with `fragment_id`, `file_path`, and `code`.

The CLI supports these execution modes:

1. **Prepared input:** the JSON provides requirements and/or code fragments.
2. **Local repository input:** `--repository` generates code fragments and capabilities automatically from the specified repository. The JSON input is optional.
3. **Exploratory input:** when no requirements are provided, the agent detects functional capabilities and evaluates completeness, correctness, and relevance.

The local repository mode preserves the existing agent input contract and adds an optional repository context.

Requirements remain optional. Automatic extraction of requirements from SRS documents is not implemented; exploratory mode does not claim compliance with real specifications.

## Repository Adapter

The repository adapter:

- Uses the shared `RepositoryAnalysisService`.
- Processes Python, JavaScript, and TypeScript source files.
- Excludes files that were not successfully processed or have no content.
- Divides source content into fragments of up to 80 lines.
- Preserves source-file paths and line ranges for traceability.
- Limits the generated collection to 500 fragments.

The adapter also derives functional capabilities from entrypoints, endpoints, functions, classes, and internal relationships. Each capability keeps traceable evidence (file, line range, symbol, and matching code fragment when available).

The adapter produces candidate evidence, not verified proof of functional compliance.

## Output Contract

The agent returns structured results containing requirement identifiers, classifications, justifications, and supporting evidence.

The classification values are:

- `cumple` — evidence supports the requirement according to the evaluation.
- `no_cumple` — evidence supports a finding of noncompliance.
- `evidencia_insuficiente` — available evidence is insufficient for a reliable conclusion, or verification could not be completed.

Classification values remain in Spanish because they are part of the existing output contract.

The output also includes requirement counts and a calculated score. These values describe the evaluated requirements and must not be interpreted as overall repository coverage.

In exploratory mode, `score` is `0.0`, `score_applicable` is `false`, and `score_meaning` states that no compliance or coverage percentage is calculated. The output adds:

- `audit_mode`: `requirements_based` or `exploratory`.
- `capabilities`: detected functional capabilities with traceable evidence.
- `findings`: completeness, correctness, and relevance findings.
- `subattributes`: qualitative summaries for `completitud`, `correccion`, and `pertinencia`.
- `classification_criteria`: explicit criteria for `confirmado`, `probable`, and `no_verificado`.
- `limitations` and `recommendations`.

Findings are classified as:

- `confirmado`: observed, traceable evidence supports the evaluated static characteristic. This does not prove compliance with real requirements.
- `probable`: evidence is partial, inferred, or incomplete.
- `no_verificado`: retained evidence or specifications are insufficient.

Exploratory mode does not execute tests, measure coverage, or claim functional correctness against unavailable specifications.

## ISO/IEC 25010 Alignment and Evaluation Criteria

### Quality model relationship

ISO/IEC 25010 defines **Functional suitability** as the quality characteristic concerned with whether a product provides functions that meet stated and implied needs. Its three subcharacteristics are:

- **Functional completeness** — the degree to which the set of functions covers all specified tasks and user objectives.
- **Functional correctness** — the degree to which the product provides correct results with the required precision.
- **Functional appropriateness** — the degree to which the functions facilitate the accomplishment of specified tasks and objectives.

The repository uses the term "functional adequacy" for the audit, but its exploratory outputs map to these three concepts. This section distinguishes what the agent currently implements, the criteria required for verifiable evaluation, and the improvements still pending. It does not assert normative conformity. The repository does not pin an ISO/IEC 25010 edition or clauses, and the standard defines a quality model rather than an evaluation method with thresholds.

### Implemented behavior

The exploratory path implements static classifications only. The current decision logic is:

| Function | Implemented decision |
|---|---|
| `_classify_completeness` | Returns `no_verificado` when the capability has no evidence. Returns `probable` when detection is `inferred`, when the snippets look like a stub, or when an entrypoint capability has no symbol evidence. Returns `confirmado` otherwise. |
| `_classify_correction` | Returns `no_verificado` when the capability has no evidence or when the snippets look like a stub. Returns `probable` when detection is `inferred` or when an entrypoint capability has no symbol evidence. Returns `confirmado` otherwise, based only on static evidence. |
| `_classify_pertinence` | Returns `no_verificado` when the capability has no evidence. Returns `confirmado` for an observed entrypoint; for non-inferred capabilities, internal relationships also yield `confirmado`. Returns `probable` for inferred detection or when only symbol evidence exists. |
| `evaluate_capabilities` | Concatenates the retained snippets, applies `_looks_like_stub`, and creates one finding per capability for `completitud`, `correccion`, and `pertinencia`, with justification, criteria, and evidence. |
| `build_subattribute_summaries` | Counts findings per attribute and reports `evaluated_capabilities`, `confirmed`, `probable`, and `unverified`. It does not calculate ratios or coverage. |

The important consequence is that `_classify_correction` can return `confirmado` when a capability has non-empty, non-stub static evidence. That is the implemented behavior. It is not evidence of functional correctness against a requirement or an oracle. The proposed criterion below therefore does not match the current behavior.

### Current state against the objective

| Subcharacteristic | Implemented behavior | Information used | Current limitation | Proposed criterion and pending improvement |
|---|---|---|---|---|
| Functional completeness | `_classify_completeness` checks evidence presence, detection kind, stub status, entrypoint kind, and symbol evidence. In requirements-based mode, each supplied requirement receives a global compliance status, but the three subcharacteristics are not reported separately. | Capability evidence (file, optional line range, symbol, fragment, and snippet), detection kind, capability kind, and requirement descriptions with retrieved fragments. | No specified task or objective model and no requirement-to-capability mapping. Helper symbols can be counted as capabilities. Test entrypoints are not excluded from entrypoint detection. Missing functionality usually appears as insufficient evidence rather than noncompliance. | Map every specified task or requirement with acceptance criteria to validated implementation locations, then measure coverage of specified behaviors. Pending: task/objective model, requirement decomposition, requirement-to-capability mapping, and negative evidence for absence after a documented search scope. |
| Functional correctness | `_classify_correction` returns `confirmado` for non-empty, non-stub static evidence when the capability is not inferred and, for entrypoints, has symbol evidence. In requirements-based mode, the model returns `cumple`, `no_cumple`, or `evidencia_insuficiente`. | Code snippets, lexical stub markers (`pass`, `...`, `NotImplementedError`, `throw new Error`, `TODO`, `FIXME`), capability metadata, and model judgement over retrieved fragments. | No execution, oracle, expected output, or precision measurement. Static non-stub code may be logically incorrect. Model judgement depends on retrieval quality and is not an independent test. | Require expected behavior and precision, an oracle, and an executed test or reproducible trace. A confirmed correctness finding should require an observed result that matches the expected behavior. Pending: oracle/execution integration, expected results, precision criteria, and a classification rule that prevents static non-stub evidence from producing confirmed correctness. |
| Functional appropriateness | `_classify_pertinence` returns `confirmado` for an observed entrypoint or, when detection is not inferred, for internal relationships. It returns `probable` for inferred detection or symbol-only evidence, and `no_verificado` without evidence. | Entrypoint kind and detection, internal import relationships, and symbol evidence. | No user task or objective model. Importing a module does not demonstrate use. Test entrypoints are not excluded. Mount prefixes and effective routes may be unresolved. | Map capabilities to specified tasks or objectives and demonstrate reachability or usage from a user-facing entrypoint or documented public API. Pending: task/objective model, usage or call-graph evidence, test-entrypoint exclusion, route resolution, and negative evidence for unrelated or unreachable capabilities. |

### Classification criteria

The output contract defines the values `confirmado`, `probable`, and `no_verificado`. The table separates their current exploratory semantics from the stricter interpretation required for verifiable evaluation.

| Classification | Current exploratory behavior | Proposed ISO/IEC 25010-aligned criterion |
|---|---|---|
| `confirmado` | Static evidence passes the checks in `_classify_completeness`, `_classify_correction`, or `_classify_pertinence`. For correctness, this includes non-empty, non-stub code without an oracle or executed result. | Observed, traceable, and sufficient evidence for the specific subcharacteristic. Completeness requires a mapping to specified tasks or requirements. Correctness requires an oracle or executed result that matches the expected behavior. Appropriateness requires a mapping to a specified task and demonstrated usage or reachability. |
| `probable` | Detection is `inferred`, completeness evidence looks like a stub, an entrypoint lacks symbol evidence, or pertinence rests only on symbol evidence. | Evidence is partial, inferred, or incomplete, or an implementation exists but its behavior has not been demonstrated. |
| `no_verificado` | The capability has no evidence; correctness also returns this value for stub-like code; pertinence returns this value when no evidence, symbol, or internal relationship supports the capability. | Evidence, specification, or execution is insufficient for a conclusion, or verification could not be completed. This is not a finding of noncompliance. |

The current `confirmado` value for `correccion` is a static classification. It does not satisfy the proposed correctness criterion and must not be interpreted as demonstrated functional correctness. A non-empty static implementation is at most evidence of presence or a probable correctness hypothesis. The same caution applies to `cumple` in requirements-based mode: it is a model judgement over retrieved evidence, not an independent execution result.

In requirements-based mode, `evidencia_insuficiente` currently groups absence of evidence, low retrieval relevance, model failure, and invalid model output. For verifiable reporting, technical failure should be distinguished from an inconclusive functional result.

### False-positive prevention criteria

A false positive is an affirmative classification that the retained evidence does not support: a `confirmado` finding in exploratory mode, or an unsupported `cumple` or `no_cumple` result in requirements-based mode. This subsection records the rules that reduce false positives in the `completitud`, `correccion`, and `pertinencia` evaluations. The per-attribute rules refer to the exploratory classifiers, because subcharacteristic findings are only produced there. Applied rules are enforced by the current code. Proposed rules are not applied yet and must not be reported as implemented behavior.

#### Completeness (`completitud`)

Applied rules:

- A capability without retained evidence is classified `no_verificado`. Missing functionality appears as insufficient evidence, never as noncompliance.
- Capabilities with `inferred` detection are downgraded to `probable`.
- Stub-looking snippets downgrade completeness to `probable`, so skeleton implementations are not confirmed as complete.
- Entrypoint capabilities without symbol evidence are downgraded to `probable`.
- Symbol candidates located in test paths are excluded from capabilities through `_is_test_path`.

Not prevented by the applied rules:

- A detected symbol, entrypoint, or import relationship is accepted as a capability, and `_classify_completeness` returns `confirmado` from non-stub static evidence. A detected symbol does not demonstrate a complete functionality: the current checks confirm the presence of static evidence, not coverage of a specified task or objective.
- Helper symbols can be counted as capabilities.
- Entrypoints located in test files are not excluded from entrypoint detection, so test-only entrypoints can be confirmed as complete production functionality.

Proposed rules (not applied):

- Confirm completeness only when the capability is mapped to a specified task or requirement with validated implementation locations.
- Exclude test-only files and entrypoints from entrypoint detection and from the evidence used for affirmative classifications.
- Do not count helper symbols as user-facing capabilities without usage evidence.
- Report noncompliance for missing functionality only from negative evidence collected after a documented search scope.

#### Correctness (`correccion`)

Applied rules:

- A capability without retained evidence is classified `no_verificado`.
- Stub-looking snippets are classified `no_verificado`, so skeleton implementations are not confirmed as correct.
- Capabilities with `inferred` detection are downgraded to `probable`.
- Entrypoint capabilities without symbol evidence are downgraded to `probable`.

Not prevented by the applied rules:

- `_classify_correction` returns `confirmado` for non-empty, non-stub static evidence. A non-empty implementation does not demonstrate correctness: static non-stub code may be logically incorrect, and no oracle, expected result, or execution participates in the classification. This is the main known false-positive source for correctness.

Proposed rules (not applied):

- A confirmed correctness finding requires an oracle or expected behavior and an executed result that matches it.
- Static, non-stub evidence must yield at most `probable` correctness; `confirmado` must not be reachable from static evidence alone.

#### Pertinence (`pertinencia`)

Applied rules:

- A capability without retained evidence is classified `no_verificado`.
- Capabilities with `inferred` detection are downgraded to `probable`.
- Symbol-only evidence yields `probable`.

Not prevented by the applied rules:

- `_classify_pertinence` returns `confirmado` for non-inferred capabilities with internal relationships. An import relationship does not demonstrate that a functionality is pertinent: importing a module does not demonstrate use, and the retained relationship labels are import facts, not usage or reachability evidence.
- Observed entrypoints are confirmed without resolving mount prefixes or effective routes, so an unmounted route can be confirmed as pertinent.
- Entrypoints located in test files are not excluded, so test-only entrypoints can be confirmed as pertinent production functionality.

Proposed rules (not applied):

- Confirm pertinence only with a mapping to a specified task or objective and demonstrated usage or reachability from a user-facing entrypoint or documented public API.
- Internal import relationships alone must not produce `confirmado`; they should yield at most `probable`.
- Exclude test-only entrypoints and files from pertinence evaluation.

#### Cross-cutting rules

Applied rules:

- Absence of evidence does not produce noncompliance. Exploratory mode has no `no_cumple` classification, and requirements-based mode routes missing evidence, retrieval failure, provider failure, and invalid model output to `evidencia_insuficiente` before any noncompliance claim.
- Exploratory evidence records are deduplicated and carry `file_path`, an optional line range, an optional symbol, `fragment_id`, and a snippet capped at 40 lines. `test_exploratory_evidence_has_valid_paths_and_lines` validates that cited files exist, line ranges are valid, and fragment identifiers resolve against the generated fragments.

Limitations of the applied rules:

- Test exclusion covers symbol candidates only. Entrypoint detection has no test-path filter, `build_code_fragments` does not exclude test files from retrieval, and the fragment fallback path in `extract_fragment_capabilities` does not filter test paths either. The Flask repository run documented in Verified Results retrieved `tests/test_apps/cliapp/app.py` as requirement evidence.
- The path markers match by substring. `test_` also matches production names such as `latest_utils.py`, while `conftest.py` is not matched at all, so fixtures and helpers defined there remain symbol candidates.
- Stub detection in `_looks_like_stub` matches the markers `pass`, `...`, `raise NotImplementedError`, `throw new Error`, `TODO`, and `FIXME` as substrings of each retained line. Accidental collisions are not prevented: `pass` matches inside `password`, `passphrase`, and `bypass`, and `TODO` matches inside `TODO_LIST`. A capability whose retained lines all contain such identifiers can be misclassified as a stub, producing unsupported downgrades for completeness and correctness. The `...` marker also collides with type hints and literals such as `Callable[..., None]`.
- In requirements-based mode, technical verification failures and inconclusive functional results share the `evidencia_insuficiente` status, and the model is not required to cite specific evidence locations.

Proposed rules (not applied):

- Match stub markers on word boundaries or as standalone statements so identifiers such as `password`, `passphrase`, and `TODO_LIST` do not trigger skeleton detection, and do not treat `...` inside type hints or literals as a stub marker.
- Exclude test-only files, entrypoints, and fragments from production capability detection and from evidence used for affirmative classifications; recognize `conftest.py` and replace substring matching on path markers.
- Require every `confirmado` finding and every `cumple` or `no_cumple` result to cite at least one resolvable reference: file, line range, and snippet or fragment.
- Keep absence of evidence and technical verification failure distinct from noncompliance, and separate technical failures from inconclusive functional results.

### Required evidence

To support a proposed functional finding, the evidence should be resolvable against the analyzed snapshot:

- File path and line range, when available.
- Related symbol, when the evidence is associated with a function, method, or class.
- Code fragment.
- Requirement or expected behavior, when one exists.
- Test and execution result, when correctness is being evaluated.
- For appropriateness, the mapping to a specified task or objective and the usage or reachability path.

The current exploratory contract stores `EvidenceLocation` records with `file_path`, optional `start_line` and `end_line`, optional `symbol`, optional `fragment_id`, and optional `snippet`. The requirements-based contract stores `CodeEvidence` records with `fragment_id`, `file_path`, `similarity`, and optional line range, symbol, and snippet. A file reference or snippet without a resolvable location is insufficient for a proposed `confirmado` finding. The requirements-based path does not require the model to cite specific evidence locations.

### Metrics

The following metrics are available from the current output schemas or result files. A **direct** value is stored in a field; a **derived** value is calculated from stored fields.

#### Metrics currently computable

| Metric | Source | Type | Availability |
|---|---|---|---|
| Detected capability count | `capabilities` array | Derived count | Exploratory mode; requirements mode has no capabilities. |
| Capabilities with retained evidence | `capabilities[].evidence` | Derived count | Exploratory mode; individual evidence locations may omit lines, symbols, or snippets. |
| Findings by subattribute and classification | `findings[]` and `subattributes[]` | Direct summary counts in `subattributes`; arbitrary cross-tabs are derived from `findings` | Exploratory mode. `build_subattribute_summaries` reports `evaluated_capabilities`, `confirmed`, `probable`, and `unverified` per attribute. |
| Requirements by status | `results[].status` | Derived count | Requirements-based mode; exploratory mode returns no requirement results. |
| Requirement totals | `total_requirements`, `fulfilled_requirements` | Direct | Requirements-based mode; both are `0` in exploratory mode. |
| Fulfilled/total score | `score` | Derived from `fulfilled_requirements / total_requirements` | Requirements-based mode; exploratory mode sets `score` to `0.0` and `score_applicable` to `false`. |
| Retrieved fragment count per requirement | `results[].evidence` | Derived count | Requirements-based mode. |
| Similarity per retrieved fragment | `results[].evidence[].similarity` | Direct | Requirements-based mode; exploratory `EvidenceLocation` has no similarity field. |
| Entrypoint capability count | `capabilities[].kind` and `capabilities[].detection` | Derived count | Exploratory mode; no separate entrypoint inventory is stored. |
| Capabilities with internal relationships | `capabilities[].relationships` | Derived count | Exploratory mode; in the repository extraction path, relationships are filtered to internal imports, exclude `contains`, and are capped at five per capability. |

These are descriptive counts of retained artifacts and static classifications. They are not ISO measures of functional completeness, correctness, or appropriateness. Derived values must be labeled as derived.

#### Metrics requiring implementation

- Functional completeness coverage: specified tasks or requirements with validated implementation divided by specified tasks or requirements.
- Functional correctness rate: cases with an oracle and an observed matching result divided by cases with an oracle.
- Functional appropriateness coverage: capabilities mapped to specified tasks and reachable or used divided by capabilities evaluated.
- Requirement-level counts of confirmed, probable, and unverified results. The current requirements-based output uses compliance statuses, not these classifications.
- Precision, recall, Recall@k, and MRR against a labeled ground truth.
- Evidence traceability rate: findings with resolvable file, line, symbol, and snippet divided by total findings.
- Counts that separate inconclusive functional results from technical verification failures.

None of these metrics are currently computed. No coverage, precision, or correctness percentages should be inferred from the existing examples.

### Terminology and limitations

- **Detected capability** — a static entity inferred from entrypoints, symbols, or code fragments. It is not a functional requirement.
- **Functional requirement** — an externally supplied requirement with an identifier and description. The current contract does not include acceptance criteria, expected results, precision, or task identifiers.
- **Verified requirement** — a requirement with an evidence-based evaluation. It is not independent proof unless supported by an oracle or execution.
- **Functional finding** — an assessment of a capability or requirement against a subcharacteristic, with evidence and a classification. A finding is not automatically a defect.

Exploratory mode evaluates detected capabilities, not requirements. Requirements-based mode evaluates supplied requirements but does not produce separate subcharacteristic findings. There is no requirement-to-capability mapping, so the current output cannot establish functional completeness coverage.

A current `confirmado` classification means that static evidence passed the implemented checks; it is not an ISO/IEC 25010 conformity statement. In particular, `confirmado` for `correccion` does not demonstrate functional correctness. Absence of evidence is not noncompliance, and a technical verification failure is not a functional finding.

## Execution

### Prepared JSON input

From the repository root:

```bash
cd agent-server
uv run functional-adequacy ../datasets/flask_validation.json \
  --output ../datasets/flask_cli_result.json \
  --provider gemini \
  --model gemini-3.8-flash
```

### Automatic local repository analysis

```bash
cd agent-server
uv run functional-adequacy ../datasets/flask_validation.json \
  --repository /path/to/local/flask \
  --output ../datasets/flask_repository_result_retry.json \
  --provider gemini \
  --model gemini-3.8-flash
```

### Exploratory audit without requirements

```bash
cd agent-server
uv run functional-adequacy \
  --repository /path/to/local/flask \
  --output ../datasets/flask_exploratory_result.json \
  --provider gemini \
  --model gemini-3.8-flash
```

Exploratory mode does not call the language model. `LLM_API_KEY` is only required for requirements-based verification. API keys must never be committed to the repository.

## Verified Results

### Flask — Prepared Input

- Requirement: `REQ-FL-001`.
- Classification: `cumple`.
- Supporting evidence: 4 code fragments.
- Gemini request: HTTP 200.
- CLI output: `datasets/flask_cli_result.json`.

### Flask — Automatic Repository Analysis

Date: October 18, 2026.

- Repository: Flask, analyzed from a local directory.
- Requirements: 1.
- Generated code fragments: 277.
- Semantically retrieved evidence fragments: 5.
- Gemini request: HTTP 200 on the successful retry.
- Classification: `cumple`.
- Structured output: `datasets/flask_repository_result_retry.json`.
- Related source evidence includes `src/flask/sessions.py` and `tests/test_basic.py`.

The retrieved evidence also included `tests/test_apps/cliapp/app.py`, whose relevance to the requirement was not demonstrated.

The reported score of 100% represents one classified requirement out of one evaluated requirement. It does not represent complete functional coverage of Flask.

### Provider Failure Case

The initial automatic repository execution received HTTP 503 from Gemini.

The agent returned `evidencia_insuficiente` and generated a structured JSON result.

Evidence: `datasets/flask_repository_result.json`.

This outcome demonstrates error handling, not a functional noncompliance finding.

### FastAPI Validation

- A functional requirement was evaluated using real source-code fragments.
- Repository tests were executed as supporting evidence.
- Result: `datasets/fastapi_validation_result_retry.json`.

### Shared Pipeline

- The `functional-adequacy` pipeline was executed successfully using the Flask prepared dataset.
- Result: `datasets/flask_pipeline_result.json`.

## Call Propagation Between Methods and Endpoints (TA-030)

This section records the technical closure of TA-030. It documents call propagation in exploratory mode and does not change the ISO/IEC 25010 criteria above.

### Implementation

#### Objective

The propagation prevents an endpoint or method from being classified as statically complete and correct when its resolved call path reaches a skeleton implementation. It uses actual resolved calls, not imports or naming similarity, so an unrelated import does not downgrade a capability.

#### Python call-resolution architecture

The exploratory path extracts calls from processed Python files using `ast`:

- `_python_import_aliases` maps local import aliases to imported names.
- `_annotation_class_names`, `_function_local_types`, and `_merged_local_types` infer receiver types from annotations, assignments, constructors, boolean expressions, and conditional expressions.
- `_receiver_class_names` resolves `self` and `cls` to the enclosing class and resolves local variables from the inferred type environment.
- `_resolve_python_call` resolves a method only when there is exactly one candidate class and one matching method, and resolves a bare function only when it is unique in the same file or in the imported project scope.
- Unresolved or ambiguous calls are omitted instead of guessed.

Each resolved call is stored as a `CapabilityCall` with the target capability identifier, target symbol, file path, line range, and source snippet. Output relationships distinguish imported modules (`importa:`) from resolved calls (`invoca:`).

#### Direct and transitive propagation

`_incomplete_call_paths` starts from the capability's resolved calls and follows the `calls` of each target capability. A direct propagation is a single resolved call to a skeleton target. A transitive propagation is a chain such as endpoint, implemented method, second implemented method, and skeleton target.

Only paths ending in an implementation classified as a skeleton produce propagation. The traversal does not propagate every `probable` or `no_verificado` classification, and it does not downgrade a capability whose resolved target is implemented.

#### Cycles, ambiguity, and non-propagated calls

The traversal keeps an active set of capability identifiers. A call whose target is already active is skipped, which prevents self-recursion and cycles such as `ping -> pong -> ping` from blocking or duplicating the analysis. Import relationships, calls with an untyped receiver, calls with multiple possible classes or methods, and JavaScript/TypeScript calls do not create propagation edges.

#### Call-site and target evidence

For every incomplete path, `_propagation_evidence` adds an `EvidenceLocation` for each resolved call in the chain and then appends the skeleton target's retained evidence. Evidence is deduplicated. Direct and transitive findings therefore retain:

- the calling endpoint or method location;
- each intermediate call-site location;
- the target method symbol and line range;
- the skeleton snippet, when retained.

The justification describes a direct call or the resolved symbol chain ending at the skeleton.

#### Inherited finding classification

An inherited incomplete path produces:

- `completitud`: `probable`;
- `correccion`: `no_verificado`.

The same rule applies to intermediate implemented methods that participate in the chain and to the skeleton target itself. This is a static dependency classification; it does not establish functional correctness or noncompliance.

### Unit tests

The five Functional Adequacy suites were executed with:

```bash
cd agent-server
uv run pytest tests/test_functional_adequacy.py \
  tests/test_functional_adequacy_exploratory.py \
  tests/test_functional_adequacy_integration.py \
  tests/test_functional_adequacy_pipeline.py \
  tests/test_functional_adequacy_repository_adapter.py -q
```

Verified result: **83 passed**.

The propagation tests cover direct calls to `NotImplementedError`, `pass`, and `...`; a single intermediate method; a multi-level chain; cycle prevention; ambiguous calls without propagation; an unrelated skeleton that must not affect an implemented method; and line-level evidence for every call in a transitive chain.

Ruff on the modified functional-adequacy source and test files passed:

```text
All checks passed!
```

`git diff --check` reported no errors.

### CLI validation

The exploratory CLI was executed against the local `functional-adequacy-demo` checkout with:

```bash
cd agent-server
uv run functional-adequacy \
  --repository /path/to/functional-adequacy-demo \
  --output ../datasets/functional_adequacy_demo_ta030_verified.json
```

Verified result:

- **34 capabilities**
- **102 findings**

The following endpoint findings include both the call site in `api.py` and the skeleton definition in `service.py`:

| Endpoint | Resolved call | Completeness | Correctness | Traceable evidence |
|---|---|---|---|---|
| `get_product` | `InventoryService.get_product` | `probable` | `no_verificado` | `src/inventory/api.py:71`; `src/inventory/service.py:28-30` |
| `delete_product` | `InventoryService.delete_product` | `probable` | `no_verificado` | `src/inventory/api.py:105`; `src/inventory/service.py:77-79` |
| `average_rating` | `InventoryService.average_rating` | `probable` | `no_verificado` | `src/inventory/api.py:113`; `src/inventory/service.py:81-83` |

### Limitations

- Propagation covers only statically resolved Python calls. Imports without a real call, dynamic calls, ambiguous receivers, unresolved attribute chains, and JavaScript/TypeScript calls are not propagated.
- The classification remains static evidence. It does not execute the repository or prove functional correctness.
- DEF-04 is not detected or propagated. In the demo, `calculate_total` contains a logical error, but it is not a skeleton. `purchase_total` records the resolved `InventoryService.calculate_total` call at `src/inventory/api.py:125`; because the target is not a skeleton, no incomplete path exists and `purchase_total` remains `confirmado` for completeness and correctness under the current static model. The current static classification does not identify the calculation error. There is no automatic logical-error detector, no universal arithmetic validator, and no hardcoded demo method name.
- Detecting logical errors requires a separate analysis capability; TA-030 only propagates skeleton findings through resolved call paths.

## Backend Integration

`POST /api/projects/:id/functional-adequacy` opens one `functional_adequacy`
execution on a project version. The request body is:

```json
{
  "branch": "main",
  "commitHash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "requirements": [
    { "requirement_id": "RF-01", "description": "The catalog lists products." }
  ]
}
```

`requirements` is optional. When it is omitted or empty, the backend creates the
version/evaluation/execution without validating or capturing a model and sends
only `root_path` to the `functional-adequacy` pipeline. This is the exploratory
path and does not require provider credentials. When requirements are present,
the saved `functional_adequacy` model is validated before any records are
created, its public configuration snapshot is stored, and `requirements` travel
with the pipeline input. The implemented user flow uses the exploratory path;
the requirements-based path remains supported by the endpoint.

The response is `201` with `versionId`, `evaluationId`, and
`executions.functional_adequacy`. Completion is reported by the agent-server
through the existing callbacks and WebSocket lifecycle; `GET
/api/projects/:id/versions` exposes the stored row and its `result`.

Backend-only validation is covered by
`backend/src/tests/project-functional-adequacy.integration.test.ts`: exploratory
runs, requirements forwarding with a captured model, missing-model rejection,
unknown projects, and empty requirement identifiers. The live crossing test now
starts the real agent-server and verifies an exploratory functional run finishes
with structured subattributes and traceable capability evidence.

## Frontend Integration

The Analyze menu offers **Functional adequacy**. The interface intentionally
starts it in exploratory mode and does not request functional requirements
manually; the HTTP client still accepts optional requirements for callers that
provide them.

Results are parsed from the execution JSON and rendered in the project
**Analysis** section as a report-style stage view:

- audit mode and, only in requirements mode, the requirement score;
- requirement results with classification, justification, and evidence;
- detected capabilities with route/symbol and file/line evidence;
- qualitative subattribute summaries for completeness, correctness, and
  relevance;
- capability findings with classification, criteria, and traceable evidence;
- limitations and recommendations.

The **Audits** section shows the functional run status and its captured
configuration when one exists. Exploratory rows intentionally have no
configuration snapshot.

EP-004 uses the project **Analysis** view as its report surface. The stored
`execution.result` is the report data, and the UI renders it with traceable
evidence. A standalone consolidated report or PDF module is out of scope for
this branch; existing “Reports” navigation entries remain placeholders.

## Automated Tests

Agent-server command:

```bash
cd agent-server
uv run pytest -q
```

Verified result on November 2, 2026:

- **291 passed**
- **0 failed**
- **1 dependency deprecation warning**

Backend command:

```bash
cd backend
pnpm test
```

Verified result on November 2, 2026:

- **183 passed**
- **0 failed**
- Includes the live backend + agent-server architecture and exploratory
  functional-adequacy crossing.

Frontend command:

```bash
cd frontend
pnpm test
```

Verified result on November 2, 2026:

- **487 passed** across 69 test files
- **0 failed**

Focused frontend validation of the Functional Adequacy result view:

```bash
cd frontend
pnpm exec vitest run src/features/project-management/PipelineResult.test.tsx
```

Verified result:

- **21 passed**
- **0 failed**
- Three of these tests correspond to `FunctionalAdequacyResultView`.

`pnpm lint` passed for backend and frontend. The modified agent-server Python
files pass `ruff check`; the full agent-server tree still has pre-existing Ruff
findings under `src/server/agents/security/`.

Five tests specifically validate the repository adapter:

- Traceable fragment generation.
- Exclusion of unsupported and unprocessed files.
- Line-range splitting.
- Maximum fragment limit.
- Requirement preservation when using the shared repository analysis service.

Test file: `agent-server/tests/test_functional_adequacy_repository_adapter.py`.

## Evidence Files

- `datasets/flask_validation.json`
- `datasets/flask_validation_result.json`
- `datasets/flask_pipeline_result.json`
- `datasets/flask_cli_result.json`
- `datasets/flask_repository_result.json`
- `datasets/flask_repository_result_retry.json`
- `datasets/fastapi_validation_result_retry.json`

## Known Limitations

1. Automatic SRS requirement extraction is not implemented; exploratory mode infers capabilities instead of recovering real requirements.
2. Automatic analysis currently accepts local repository paths, not direct GitHub URLs or ZIP archives through this CLI.
3. Fixed-size fragment splitting can separate related code across fragments.
4. The 500-fragment limit can exclude relevant code from large repositories.
5. Semantic retrieval can select irrelevant fragments, and language-model classifications require independent validation.
6. A language-model provider failure can result in `evidencia_insuficiente`; this must not be interpreted as functional noncompliance.
7. Exploratory findings are static indicators, not proof of correctness, coverage, or compliance with real specifications.
8. The interface intentionally exposes exploratory runs only; requirements-based runs remain an API capability outside the implemented user flow.
9. The report surface is the project Analysis view over the stored execution result; a standalone consolidated/PDF report is out of scope for this branch.
10. The live crossing verifies the exploratory path. Requirements-based runs have integration and unit coverage, but no live provider-backed execution is part of the automated suite.
11. The evaluated examples do not establish overall functional coverage or general classification accuracy.

## Integration Notes

The local repository adapter is implemented within EP-004 and reuses VERAUD's shared repository analysis service.

Backend, persistence, callbacks, and the project Analysis view now use the existing execution architecture. No parallel invocation path was added. The endpoint supports both exploratory and requirements-based runs, while the UI currently exposes exploratory runs only. Exploratory mode is the intended user flow for EP-004.

EP-004 deliberately closes with the project Analysis view as its report surface; consolidated/PDF reporting is out of scope for this branch. The existing agent, pipeline, and output contracts should continue to be reused rather than creating a separate execution architecture.

### Shared operating configuration

Both modes retain the existing quality-audit endpoint and configuration flow.
Saved category settings and per-run `attribute_options.functional_adequacy` accept:

- `agent_defaults`: the existing context, output-token, personal-token and model-call
  controls. The functional drawers omit the tool-call control because this agent
  reads a retained snapshot rather than calling repository tools. Legacy shared
  patches remain accepted for compatibility with combined audits.
- `functional_config`: `embedding_model`, `retrieval_top_k`, `timeout_seconds`,
  `max_wall_time_seconds`, `cancellation_grace_seconds`, `provider_rate_limits`
  (RPM/TPM), and the shared provider request timeout, retry count, spacing,
  backoff, per-recovery wait and cumulative recovery-wait controls.
- `audit_budget`: the existing audit-wide token budget, separate from the
  attribute's personal allowance.

All added controls derive their types, defaults and validation from the owning
shared configuration classes; no second parameter/default catalog is maintained.
An omitted quota retains its effective value; an explicit `null` disables only
that quota and survives validation, persistence and per-run merging. An explicit
functional active-time cap cannot be widened by the root transport timeout.

Time limits apply to both modes. Provider, token, context and model-call controls
govern only requirements-based model work; exploration still requires no model,
credentials or SBERT. Structured-output repair and tool controls are not added to
`functional_config`: the graph does not implement those mechanisms. Static
extraction constants and default classifications remain unchanged. The existing
process-wide `unlimited_token_budget` policy is also unchanged; finite cumulative
token caps are enforced only when that policy enables them.

Exploratory capabilities retain the repository analyzer's detection categories:
`declared`, `observed` and `inferred`. A declaration is not promoted to an observed
implementation or proof of functional correctness. Contract validation failures
log only known schema/field names and validation types to the agent console;
rejected values and repository contents are excluded, and public errors remain
subject to the existing shared privacy policy.

### Integration regression checks

- `test_functional_adequacy_characterization.py`: complete output fingerprints captured
  from pre-merge commit `ad4e0b3`, with controlled retrieval and provider responses.
- `test_functional_audit_configuration.py`: effective runtime schemas, partial/null
  quota merging, actual model-call/context/token admission, provider timeout and
  retries, and time limits in both modes.
- `test_functional_quality_audit.py`: exact direct/audit output equality, one shared
  snapshot, three exploratory subattributes, evidence links, invocation phases,
  JSON/Word reports, no functional model calls and partial status without source.
- Backend `quality-audit.integration.test.ts`: the existing endpoint/response shape,
  independent and combined exploration, no functional credentials, history, report
  delivery, duplicate-run prevention and requirements-mode configuration enforcement.
- Frontend `QualityAudits.test.tsx`: automatic mode selection from the requirements
  editor and readiness checks only for model-backed attributes.

## Git References

- `c685d17` — Initial FastAPI validation evidence.
- `2e6dc96` — Shared pipeline integration.
- `12fb0b4` — Functional Adequacy CLI and Flask execution evidence.
- `3de4862` — Initial Functional Adequacy technical documentation.