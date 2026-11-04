# EP-004 — Functional Adequacy

## Overview

The Functional Adequacy module evaluates software requirements against source-code evidence, or explores static capabilities when requirements are absent, and produces structured, traceable findings.

The module is part of VERAUD's shared multi-agent architecture. It is not a standalone auditing system.

## Architecture

The `functional_adequacy` agent is registered through `AgentExecutionService` and exposed through the `functional-adequacy` pipeline using `GenericPipelineService`.

With requirements, the agent uses semantic retrieval with `sentence-transformers/all-MiniLM-L6-v2` to rank candidate code fragments. A language model then evaluates the retrieved evidence and generates a classification with supporting justification. Without requirements, the graph selects deterministic static exploration: no embedding model, provider client or credentials are needed.

The `repository_adapter.py` component reuses the shared `RepositoryAnalysisService` to transform source files from a local repository into the agent's existing input contract.

The repository adapter is a supporting component, not an additional agent.

Semantic similarity alone does not establish functional compliance.

## Input Contract

The agent accepts a JSON object containing:

- `requirements`: optional objects with `requirement_id` and `description` (maximum 100). Missing or empty requirements select exploration.
- `code_fragments`: objects with `fragment_id`, `file_path`, and `code`.
- `repository_context`: optional retained capabilities, analysis limitations and incidents.

The CLI supports two execution modes:

1. **Prepared input:** the JSON provides both requirements and code fragments.
2. **Local repository input:** `--repository` generates code fragments and capability context automatically. The input JSON may be omitted for exploration.

The local repository mode preserves the existing agent input contract.

Explicit requirements are supplied in structured JSON. Inferred static capabilities are not specifications; automatic extraction of requirements from SRS documents is not implemented.

## Repository Adapter

The repository adapter:

- Uses the shared `RepositoryAnalysisService`.
- Processes Python, JavaScript, and TypeScript source files.
- Excludes files that were not successfully processed or have no content.
- Divides source content into fragments of up to 80 lines.
- Preserves source-file paths and line ranges for traceability.
- Limits the generated collection to 500 fragments.

The adapter produces candidate evidence, not verified proof of functional compliance.

## Output Contract

The agent returns structured results containing requirement identifiers, classifications, justifications, and supporting evidence.

The classification values are:

- `cumple` — evidence supports the requirement according to the evaluation.
- `no_cumple` — evidence supports a finding of noncompliance.
- `evidencia_insuficiente` — available evidence is insufficient for a reliable conclusion, or verification could not be completed.

Classification values remain in Spanish because they are part of the existing output contract.

The output also includes requirement counts and a calculated score. These values describe the evaluated requirements and must not be interpreted as overall repository coverage.

Exploration returns `audit_mode="exploratory"`, `score_applicable=false`, no requirement results, capabilities, findings and summaries for `completitud`, `correccion` and `pertinencia`. Each finding retains `confirmado`, `probable` or `no_verificado`, criteria, justification and evidence. A confirmed static indicator is not verified functional correctness. No compliance/coverage percentage is displayed in this mode; `score=0` is only a compatibility placeholder.

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

The `LLM_API_KEY` environment variable must be configured for requirements-based execution. API keys must never be committed to the repository. Exploration can run without it:

```bash
uv run functional-adequacy --repository /path/to/repository --output exploratory-result.json
```

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

### Automated Tests

Command:

```bash
cd agent-server
uv run pytest -q
```

Verified result on October 18, 2026:

- **270 passed**
- **0 failed**
- **1 dependency deprecation warning**
- Execution time: 24.65 seconds

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

1. Explicit requirements must be supplied as structured JSON; exploration does not replace specifications or implement SRS requirement extraction.
2. Automatic analysis currently accepts local repository paths, not direct GitHub URLs or ZIP archives through this CLI.
3. Fixed-size fragment splitting can separate related code across fragments.
4. The 500-fragment limit can exclude relevant code from large repositories.
5. Semantic retrieval can select irrelevant fragments, and language-model classifications require independent validation.
6. A language-model provider failure can result in `evidencia_insuficiente`; this must not be interpreted as functional noncompliance.
7. Project quality audits prepare code fragments and capability context from the selected revision's shared snapshot. Optional requirements are entered one per line in the frontend; automatic extraction from an SRS remains unsupported.
8. Consolidated reporting uses the existing JSON and Word formats; PDF generation is not implemented.
9. The evaluated examples do not establish overall functional coverage or general classification accuracy.

## Integration Notes

The local repository adapter is implemented within EP-004 and reuses VERAUD's shared repository analysis service.

The project frontend offers **Adecuación funcional** alongside Maintainability and
Security. The visible selection is **Functional adequacy · exploratory**, independently
or combined with other attributes. It always submits an empty requirements list and
requires no functional model configuration. Only active-time, wall-time and cancellation
grace controls are shown for this mode, including in Settings → Audit.

**Functional adequacy · requirements-based (LLM)** is retained as a hidden UI variant.
Its implementation, model assignments, operating settings and API support remain
available; only its frontend editor and model/credential controls are hidden. Saving
exploratory time limits preserves all saved hidden LLM settings. Existing audit history,
reports and evidence remain accessible and are not relabeled as exploratory.

`POST /api/projects/:id/audits` accepts `functional_adequacy` in `attributes` and
optionally accepts `functional_requirements: [{ requirement_id, description }]`.
Omitted or empty requirements select exploration. The independent project endpoint
`/functional-adequacy` is not registered. The backend validates distinct IDs and,
only for model-backed attributes, model access before creating an execution.
The existing `quality-audit` pipeline shares one repository snapshot, run ID,
Blackboard and report across all selected attributes. Functional model calls use
the managed provider, shared token ledger, deadlines, pacing and live invocation
callbacks. A failure in one attribute preserves the other attributes' results.

Functional classifications and original justifications are retained per requirement
in report findings, with source fragments and the original structured output in
the Blackboard. Exploratory findings are published through the same existing
`Finding`, `Evidence` and `Assessment` contracts, with the unchanged agent output
retained in `Assessment.details.functional_output`. Empty evidence produces a
partial audit rather than a successful coverage claim. Semantic retrieval and LLM classifications are inconclusive
observations, not independently verified functional tests. Provider failures and
missing evidence remain `evidencia_insuficiente`, not `no_cumple`.

Install declared dependencies with `uv sync` before running the server. The first
functional audit loads the configured Sentence Transformers embedding model; its
download/inference runs off the server event loop. Retrieval remains capped at 500
fragments and 80 lines per fragment, as in the original repository adapter.

The shared executor, pipeline service, execution-store interfaces, callback contracts
and database schema remain those of `main`. A domain-only adapter opens a standard
`QualityAudit` execution without a fabricated model snapshot for standalone
exploration, then reuses the existing dispatch, recovery and cancellation lifecycle.
Combined audits retain their configured root and omit the unused functional model.

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
