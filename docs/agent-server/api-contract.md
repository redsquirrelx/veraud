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
  - `model.provider`: `"gemini"`/`"google"`, `"openrouter"`/`"openai"`, `"groq"`, or `"anthropic"`.
  - Groq uses `https://api.groq.com/openai/v1`. Set `model.name` to a model available in your Groq account and provide a Groq key through `config.api_key` or the server's `LLM_API_KEY`. When switching from another provider to Groq, `model.name` is required so a Gemini/OpenRouter model name is not inherited accidentally.
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

## `GET /api/pipelines`

```json
["project-architecture"]
```

## `POST /api/pipelines/{name}/run`

Runs a registered pipeline by name under a shared deadline. The only
registered pipeline is `project-architecture`: orientation, then
architecture, then semantic validation over one retained snapshot. Later
stage inputs are derived server-side, so the caller only sends the
repository root plus budgets and flags.

Source of truth: `agent-server/src/server/api/pipelines.py`,
`agent-server/src/server/app/pipeline_service.py`,
`agent-server/src/server/app/project_architecture_definition.py`.

### Request

```json
{
  "input": {
    "root_path": "/path/to/checkout",
    "max_files": 5000,
    "max_depth": 30,
    "include_orientation": true,
    "validate_semantics": true,
    "allow_return": true,
    "include_diagram": true
  },
  "config": {},
  "stage_configs": {
    "orientation": {},
    "architecture": {},
    "semantic_validation": {}
  },
  "execution_ids": { "orientation": 11, "architecture": 12, "semantic_validation": 13 },
  "timeout_seconds": 600
}
```

- `input.root_path` (string, required): checkout directly inside the shared
  workspace (see `WORKSPACE_ROOT`). Budgets (`max_model_calls`,
  `max_tool_calls`, `max_total_tokens`, ...) and flags mirror the
  `run_project_architecture` CLI defaults.
- `config` (object, optional): shared model/credential overrides.
- `stage_configs` (object, optional): per-stage `ExecutionConfig` entries.
  The backend supplies every saved stage configuration explicitly, including
  credentials. Each stage uses its own entry instead of `config`.
- `execution_ids` (object, optional): rows the backend created for this run.
  When present each stage reports its own progress back to its row
  (`running`, then `Completed`/`Failed`, or `Failed` with a `Skipped:`
  error when the graph does not run it); absent means nobody is listening
  and nothing is reported, like the dev runners.
- `timeout_seconds` (int > 0, default `600`): deadline for the whole
  pipeline, enforced around the graph. There are no per-stage timeouts.

### Reporting

```
mark_running(orientation) -> orientation.run() -> complete(orientation, Completed)
mark_running(architecture) -> architecture.run() -> complete(architecture, Completed)
mark_running(semantic_validation) -> ... -> complete(semantic_validation, Completed)
```

- A stage that the graph skips (e.g. semantic review without an
  architecture report) closes as `Failed` with a `Skipped:` error, so no row
  hangs in `Waiting`. The internal `diagram_composition` node has no row.
- A stage fails → its row closes as `Failed`, later stages close as `Failed`
  with a `Skipped:` error.
- A pipeline timeout fails every row still open with a timeout error.
- Callback delivery failures never fail the run: they are logged with
  `acknowledged: false`, same as single-agent runs.

### Response `200`

The pipeline result as plain JSON (`orientation`, `architecture`,
`semantic_validation`, `diagram`, `stages`, ...). Every stage output is
opaque here, matching each agent's own output schema.

### Errors

| Code | Meaning |
|---|---|
| `404` | Unknown pipeline `name` |
| `422` | Bad config, bad input, or an unreadable `root_path` |
| `504` | Pipeline timed out |
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
