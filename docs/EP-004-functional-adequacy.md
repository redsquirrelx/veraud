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
with the pipeline input.

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

The Analyze menu offers **Functional adequacy**. The current UI always starts it
in exploratory mode because the requirements form has not been designed yet; the
HTTP client already accepts optional requirements for a future form.

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
8. The API accepts requirements, but the frontend still has no requirements input form, so UI runs are exploratory only.
9. The report surface is the project Analysis view over the stored execution result; a standalone consolidated/PDF report is out of scope for this branch.
10. The live crossing verifies the exploratory path. Requirements-based runs have integration and unit coverage, but no live provider-backed execution is part of the automated suite.
11. The evaluated examples do not establish overall functional coverage or general classification accuracy.

## Integration Notes

The local repository adapter is implemented within EP-004 and reuses VERAUD's shared repository analysis service.

Backend, persistence, callbacks, and the project Analysis view now use the existing execution architecture. No parallel invocation path was added. The endpoint supports both exploratory and requirements-based runs, while the UI currently exposes exploratory runs only.

The remaining UI gap is the requirements input form. EP-004 deliberately closes with the project Analysis view as its report surface; consolidated/PDF reporting is out of scope for this branch. The existing agent, pipeline, and output contracts should continue to be reused rather than creating a separate execution architecture.

## Git References

- `c685d17` — Initial FastAPI validation evidence.
- `2e6dc96` — Shared pipeline integration.
- `12fb0b4` — Functional Adequacy CLI and Flask execution evidence.
- `3de4862` — Initial Functional Adequacy technical documentation.