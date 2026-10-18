# EP-004 — Functional Adequacy

## Overview

The Functional Adequacy module evaluates software requirements against candidate source-code evidence and produces structured, traceable findings.

The module is part of VERAUD's shared multi-agent architecture. It is not a standalone auditing system.

## Architecture

The `functional_adequacy` agent is registered through `AgentExecutionService` and exposed through the `functional-adequacy` pipeline using `GenericPipelineService`.

The agent uses semantic retrieval with `sentence-transformers/all-MiniLM-L6-v2` to rank candidate code fragments. A language model then evaluates the retrieved evidence and generates a classification with supporting justification.

Semantic similarity alone does not establish functional compliance.

## Input Contract

The current input is a JSON object containing:

- `requirements`: objects with `requirement_id` and `description`.
- `code_fragments`: objects with `fragment_id`, `file_path`, and `code`.

Requirements and code fragments must currently be prepared before execution.

## Output Contract

The agent returns structured results containing the requirement identifier, classification, justification, and supporting evidence.

The classification values are:

- `cumple` — sufficient evidence supports the requirement.
- `no_cumple` — evidence supports a finding of noncompliance.
- `evidencia_insuficiente` — available evidence is insufficient for a reliable conclusion.

Classification values remain in Spanish because they are part of the existing output contract.

## Execution

From the repository root:

```bash
cd agent-server
uv run functional-adequacy ../datasets/flask_validation.json \
  --output ../datasets/flask_cli_result.json \
  --provider gemini \
  --model gemini-3.8-flash
```

The `LLM_API_KEY` environment variable must be configured. API keys must never be committed to the repository.

## Verified Results

**Flask validation**

- Requirement: `REQ-FL-001`.
- Classification: `cumple`.
- Supporting evidence: 4 code fragments.
- Gemini request: HTTP 200.
- CLI output: `datasets/flask_cli_result.json`.

**FastAPI validation**

- A functional requirement was evaluated using real source-code fragments.
- Repository tests were executed as supporting evidence.
- Result: `datasets/fastapi_validation_result_retry.json`.

**Shared pipeline**

- The `functional-adequacy` pipeline was executed successfully using the Flask dataset.
- Result: `datasets/flask_pipeline_result.json`.

**Automated tests**

- `uv run pytest -q`
- Result: **265 passed, 1 dependency warning**.
- Date: October 18, 2026.

## Evidence Files

- `datasets/flask_validation.json`
- `datasets/flask_validation_result.json`
- `datasets/flask_pipeline_result.json`
- `datasets/flask_cli_result.json`
- `datasets/fastapi_validation_result_retry.json`

## Known Limitations

1. The CLI currently requires prepared requirements and code fragments.
2. Automatic extraction from GitHub URLs or ZIP archives is not implemented in this module.
3. The backend currently supplies `root_path` to pipeline execution, while this module requires structured requirements and code fragments.
4. End-to-end backend integration and consolidated PDF reporting have not been verified.
5. The evaluated examples do not establish overall functional coverage or general classification accuracy.

## Integration Notes

The integration team must provide an adapter that transforms repository analysis inputs into the module's input contract and connects its structured output to the shared execution and reporting workflow.

The existing agent and pipeline contracts should be reused rather than creating a separate execution architecture.

## Git References

- `c685d17` — Initial FastAPI validation evidence.
- `2e6dc96` — Shared pipeline integration.
- `12fb0b4` — Functional Adequacy CLI and Flask execution evidence.