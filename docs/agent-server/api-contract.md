# Agent Server API

Base URL (dev): `http://localhost:7502`
Source of truth: `agent-server/src/server/api/schemas.py` (contract), `agent-server/src/server/api/executions.py` (controller)

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
  - `model.provider`: `"gemini"`/`"google"` or `"openrouter"`/`"openai"`.
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
