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
  - `model.provider`: `"gemini"`/`"google"`, `"openrouter"`/`"openai"`, or `"anthropic"`.
    OpenAI uses `https://api.openai.com/v1`; OpenRouter uses
    `https://openrouter.ai/api/v1`. Google applies temperature and maximum output tokens.
    Anthropic uses its native client with the saved model, key and generation parameters.
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

## `POST /api/agents/verify-access`

Accepts `{ "model": { "provider": "OpenAI", "name": "MODEL_NAME" }, "api_key": "PROVIDER_KEY" }`.
Provider, model and key must be explicit; no server credential fallback is used.
Performs a minimal generation request with a 25-second deadline and returns
`{ "verified": true }`. The request may incur provider usage. Denied access or
unsupported configuration returns `422`; timeout returns `504`. Error messages
do not contain provider response bodies or API keys. Request validation errors
omit input values to avoid echoing credentials.

Backend-started executions provide their saved configuration explicitly. See
[backend agent settings](../backend/agent-settings.md) for access gates and
immutable execution snapshots.
