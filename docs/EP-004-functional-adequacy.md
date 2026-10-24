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

The CLI supports two execution modes:

1. **Prepared input:** the JSON provides both requirements and code fragments.
2. **Local repository input:** the JSON provides requirements, and `--repository` generates code fragments automatically from the specified repository.

The local repository mode preserves the existing agent input contract.

Requirements must still be supplied in structured JSON. Automatic extraction of requirements from SRS documents is not implemented.

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

The `LLM_API_KEY` environment variable must be configured. API keys must never be committed to the repository.

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

1. Requirements must be supplied as structured JSON; automatic SRS requirement extraction is not implemented.
2. Automatic analysis currently accepts local repository paths, not direct GitHub URLs or ZIP archives through this CLI.
3. Fixed-size fragment splitting can separate related code across fragments.
4. The 500-fragment limit can exclude relevant code from large repositories.
5. Semantic retrieval can select irrelevant fragments, and language-model classifications require independent validation.
6. A language-model provider failure can result in `evidencia_insuficiente`; this must not be interpreted as functional noncompliance.
7. Project quality audits now supply explicit requirements and prepare code fragments from the selected revision's shared snapshot. Requirements are entered one per line in the frontend; automatic extraction from an SRS remains unsupported.
8. Consolidated reporting uses the existing JSON and Word formats; PDF generation is not implemented.
9. The evaluated examples do not establish overall functional coverage or general classification accuracy.

## Integration Notes

The local repository adapter is implemented within EP-004 and reuses VERAUD's shared repository analysis service.

The project frontend offers **Adecuación funcional** alongside Maintainability and
Security. Select it independently or combine attributes. Configure its model and
credential under Settings → Audit, then enter 1–100 functional requirements (one
per line) before starting the audit. The UI assigns stable request-local IDs
`REQ-001`, `REQ-002`, etc.

`POST /api/projects/:id/audits` accepts `functional_adequacy` in `attributes` and
requires `functional_requirements: [{ requirement_id, description }]` when selected.
The backend validates distinct IDs and model access before creating an execution.
The existing `quality-audit` pipeline shares one repository snapshot, run ID,
Blackboard and report across all selected attributes. Functional model calls use
the managed provider, shared token ledger, deadlines, pacing and live invocation
callbacks. A failure in one attribute preserves the other attributes' results.

Functional classifications and original justifications are retained per requirement
in report findings, with source fragments and the original structured output in
the Blackboard. Semantic retrieval and LLM classifications are inconclusive
observations, not independently verified functional tests. Provider failures and
missing evidence remain `evidencia_insuficiente`, not `no_cumple`.

Install declared dependencies with `uv sync` before running the server. The first
functional audit loads the configured Sentence Transformers embedding model; its
download/inference runs off the server event loop. Retrieval remains capped at 500
fragments and 80 lines per fragment, as in the original repository adapter.

The existing agent, pipeline, and output contracts should be reused rather than creating a separate execution architecture.

## Git References

- `c685d17` — Initial FastAPI validation evidence.
- `2e6dc96` — Shared pipeline integration.
- `12fb0b4` — Functional Adequacy CLI and Flask execution evidence.
- `3de4862` — Initial Functional Adequacy technical documentation.
