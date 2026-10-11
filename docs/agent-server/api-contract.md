# Agent Server API

Base URL (dev): `http://localhost:7502`
Source of truth: `agent-server/src/server/api/schemas.py` (contract), `agent-server/src/server/api/executions.py` (controller), `agent-server/src/server/api/pipelines.py` (pipelines)

Every execution is traced to LangSmith when `LANGSMITH_API_KEY` is set. See
[tracing.md](tracing.md).

## `GET /api/status`

```json
{ "status": "ok", "service": "agent-server" }
```

## `GET /api/agents`

```json
["dummy"]
```

## `POST /api/agents/run`

Run an agent by `agent_type`. The server instantiates the matching agent
class, assigns it the base config from `dev_agents_config` (overridden by
`config`), runs it, returns the audit report. Stateless: safe to retry.

### Request

```json
{
  "agent_type": "dummy",
  "config": {
    "model": {
      "provider": "gemini",
      "name": "gemini-3.1-flash-lite",
      "temperature": 0.2,
      "max_tokens": 1000
    },
    "timeout_seconds": 60,
    "api_key": null
  },
  "input": {
    "code": "def f(items):\n    return sum(items)\n",
    "evaluated_attribute": "maintainability"
  }
}
```

- `agent_type` (string, required): registered agent id.
- `config` (object, optional): all fields optional.
  - `model.provider`: `"gemini"`/`"google"`, `"openrouter"`/`"openai"`, or `"groq"`.
  - Groq uses `https://api.groq.com/openai/v1`. Set `model.name` to a model available in your Groq account and provide a Groq key through `config.api_key` or the server's `LLM_API_KEY`. When switching from another provider to Groq, `model.name` is required so a Gemini/OpenRouter model name is not inherited accidentally.
  - `model.name` / `model.temperature` / `model.max_tokens`.
  - `timeout_seconds` (int > 0): execution timeout.
  - `api_key`: credential override; server key when omitted.
  - Missing fields fall back to `agent-server/config/dev-agents.yaml`,
    then built-ins (`gemini` / `0.2` / `1000` / `60s`).
- `input.code` (string, required): code under audit.
- `input.evaluated_attribute` (string): default `"maintainability"`.

### Response `200`

```json
{
  "agent_type": "dummy",
  "result": {
    "evaluated_attribute": "maintainability",
    "score": 85.0,
    "findings": [
      {
        "title": "print() used for debugging",
        "description": "print() should not remain in auditable code.",
        "severity": "low"
      }
    ],
    "recommendations": ["Replace print() with structured logging."]
  }
}
```

- `result.score`: 0–100. `result.findings[].severity`: `low`/`medium`/`high`.

### Errors

| Code | Meaning |
|---|---|
| `404` | Unknown `agent_type` |
| `422` | Bad config or payload (unsupported provider, missing `model.name`, `timeout_seconds <= 0`) |
| `504` | Execution timed out |

## `POST /api/pipelines/architecture-audit/run`

Runs the analyzer then the architect as one pipeline: what kind of project
it is, then how it is put together. The architect's input is derived
server-side from the analyzer's output, so the caller only sends the
repository root.

Source of truth: `agent-server/src/server/api/pipelines.py`,
`agent-server/src/server/app/pipeline_service.py`.

### Request

```json
{
  "input": {
    "root_path": "/path/to/checkout",
    "max_files": 500,
    "max_depth": 8,
    "max_read_rounds": 3,
    "max_files_per_round": 8
  },
  "config": {},
  "execution_ids": { "analyzer": 11, "architect": 12 },
  "timeout_seconds": 600
}
```

- `input.root_path` (string, required): repository root to audit.
- `input.max_files` / `max_depth` / `max_read_rounds` / `max_files_per_round`: collection and reading budgets. `max_read_rounds` (default `3`) bounds both agents' re-read loops: the analyzer's confirm loop and the architect's coverage loop.
- `config` (object, optional): same per-request model overrides as `/api/agents/run`; missing fields fall back to `agent-server/config/dev-agents.yaml`.
- `execution_ids` (object, optional): rows the backend created for this run. When present each stage reports its own progress back to its row (`running`, then `Completed`/`Failed`); absent means nobody is listening and nothing is reported, like the dev runners.
- `timeout_seconds` (int > 0, default `600`): deadline for the whole pipeline, enforced around the graph. There are no per-stage timeouts: a slow stage consumes the shared budget.

### Reporting

```
mark_running(analyzer) -> analyzer.run() -> complete(analyzer, Completed)
mark_running(architect) -> architect.run() -> complete(architect, Completed)
```

- The analyzer closing as `Completed` is what feeds the architect; the backend never builds the architect input itself.
- The architect re-reads until every key component carries a responsibility line, up to `max_read_rounds`, stopping early when coverage stalls. Earlier descriptions survive later rounds.
- The architect groups files into at most 5 `containers` (C4 level 2) from what it read; invented members and empty containers are dropped. Third-party dependencies are grouped by architectural role into at most 6 `externals` (a single "third-party" group when no roles emerge); invented members are dropped.
- `diagram_containers` and `diagram_components` are derived Mermaid blocks: names and membership are model judgment, every arrow is a real import (container to container, or container to external group via member imports), provided interfaces are collected top-level symbols, cycles render red, ungrouped externals collapse into one floating box. Capped at 40 nodes / 60 edges with a `truncated` comment.
- Analyzer fails → its row closes as `Failed` and the architect row closes as `Failed` with a `Skipped:` error, so no row hangs in `Waiting`.
- Architect fails → the analyzer row stays `Completed`, the architect row closes as `Failed`.
- A pipeline timeout fails every row still open with a timeout error.
- Callback delivery failures never fail the run: they are logged with `acknowledged: false`, same as single-agent runs.

### Response `200`

```json
{
  "analysis": { "kind": "library", "confidence": "high", "...": "..." },
  "description": { "style": "layered", "...": "..." }
}
```

Both outputs opaque here, matching each agent's own output schema.

### Errors

| Code | Meaning |
|---|---|
| `422` | Bad config, bad input, or an unreadable `root_path` |
| `504` | Pipeline timed out |

## Judge agent (CLI-only)

Grades a past architecture description against its cited source: whether
each responsibility and quality note is `supported`, `contradicted`, or
`unverifiable`. Blind by design — it never sees the run's confidence.

Source of truth: `agent-server/src/server/agents/judge/`,
`agent-server/src/server/run_judge.py`.

```bash
uv run --no-sync python -m server.run_judge <root> <description.json> --json
```

Same model by construction: the runner resolves the architect's model and
hands that instance to the judge. There is no `judge` entry in
`dev-agents.yaml` to drift out of sync. Evidence cites line intervals as
`path:L1-L2` (bare path means the whole file); the judge re-reads exactly
those lines plus context, and ranges pointing outside their file land in
`unverifiable`. Every verdict names its evidence: a supported or
contradicted verdict with no checkable evidence is demoted to
`unverifiable`. Empty claims and unreadable evidence
are `unverifiable` without spending a model call; unparseable grader answers
fail toward `unverifiable`, never toward trust. The headline metric is the
contradiction rate: shared-model agreement may be self-agreement, but a
contradiction is evidence.
