# Using the agent-server

Consult `/docs` for current request/response definitions and examples.

## Discover, inspect, execute

1. Call `GET /api/agents` to discover registered agent names. Currently this
   returns `["analyzer", "architect", "dummy", "judge"]` in alphabetical order.
2. Call `GET /api/agents/{agent_type}/schema` for the selected agent. Its
   `input_schema` describes the `input` object; `output_schema` describes the
   returned `result`. These are Pydantic-generated JSON Schema documents.
   Nested references, including `$defs`, resolve inside each document.
3. Call `POST /api/agents/run` with `agent_type`, the matching `input`, and any
   configuration overrides.

The run request waits for execution and returns `{ agent_type, result }` with
the output as an object. It does not create a queued-job acknowledgement. The
backend's execution-start operation runs its work in the background instead.

## Request examples

Swagger has named examples for both agents. They explicitly select an admitted
provider because the current base configuration uses `groq`, while the model
factory supports `gemini`/`google`, `openrouter`/`openai` and `anthropic`. A request using
the current base provider without an override returns a configuration `422`.
The examples require suitable provider credentials and are not offline runs.

### Dummy: audit a code snippet

```json
{
  "agent_type": "dummy",
  "config": {
    "model": {
      "provider": "openrouter",
      "name": "openai/gpt-oss-120b"
    },
    "timeout_seconds": 60
  },
  "input": {
    "code": "def add(a, b): return a + b",
    "evaluated_attribute": "maintainability"
  }
}
```

The output includes the evaluated attribute, a score, findings and
recommendations. Omitting `evaluated_attribute` uses `maintainability`.

### Analyzer: describe a repository

```json
{
  "agent_type": "analyzer",
  "config": {
    "model": {
      "provider": "openrouter",
      "name": "openai/gpt-oss-120b"
    },
    "timeout_seconds": 120
  },
  "input": {
    "root_path": "C:/workspace/example-repository",
    "max_files": 500,
    "max_depth": 8,
    "max_read_rounds": 2,
    "max_files_per_round": 8
  }
}
```

`root_path` must be accessible on the agent-server filesystem, not the browser's
machine. The collection options shown are the input model defaults. The output
describes project kind, summary, language, entrypoints, key components and the
evidence behind the description.

## Configuration resolution

Backend-started executions provide the saved model, credential and resolved
generation parameters explicitly after a live access check. They do not use
the YAML model/provider/key defaults. OpenAI and OpenRouter use their respective
provider endpoints; Google generation applies both temperature and token limit.
The fallback rules below apply to requests with omitted overrides.

Overrides are merged with `agent-server/config/dev-agents.yaml`. Omitting
`config` creates the default ExecutionConfig; omitting `config.model` creates
an empty ModelConfig. These objects cannot themselves be `null`.

| Override | Resolution |
| --- | --- |
| `model.provider` | Truthy override, otherwise base value, otherwise `gemini`; case-insensitive provider matching |
| `model.name` | Truthy override, otherwise base value; the resolved name must be present |
| `model.temperature` | Override unless null, otherwise base value or `0.2` |
| `model.max_tokens` | Override unless null, otherwise base value or `1000` |
| `timeout_seconds` | Override unless null, otherwise base value or `60`; service rejects values <= 0 |
| `api_key` | Truthy override, otherwise server key; invalid server settings trigger the development-key fallback |

Empty provider/name/key strings follow fallback behavior. Numeric zero remains
an explicit override for temperature and max_tokens. Provider-specific ranges
are not enforced by the HTTP models. Optional scalar overrides accept `null`;
required fields remain required. Unknown model fields are ignored by default.

The timeout covers the agent run; configuration and callback delivery are
outside that interval. Configuration is resolved before input validation, so
configuration failures may be returned before an invalid agent input is found.

## Backend lifecycle callbacks

Without `execution_id`, the agent-server sends no callbacks. When the backend
has created an execution row, it can pass its positive ID. With backend settings
available, the agent-server reports:

1. Running: `POST /api/agent-executions/{execution_id}/running` with `{}`.
2. Completed: `POST /api/agent-executions/{execution_id}/completion` with a
   Completed outcome and the result serialized as a JSON string.
3. Failed: the same completion endpoint with a Failed outcome and error message.

The destination is `http://localhost:<PORT_BACKEND>`. These are outgoing calls
to the backend, not agent-server routes. Missing backend settings disable
reporting. Callback transport failures or non-success responses do not discard
the agent result. Configuration and input failures occur before the reporting
block and do not send these lifecycle callbacks.

The run HTTP response uses a nested result object; the completion callback uses
a JSON-string result. The backend owns the execution row and its ID.

## Errors

- `404`: unregistered agent. The YAML's `architect` entry is currently not
  registered; discover names from `/api/agents` instead of the config file.
- `422`: FastAPI request validation returns a `detail` array; domain failures
  for configuration, agent input or missing files return a `detail` string.
- `504`: `{"detail":"Agent execution timed out"}`.

Swagger describes both `422` shapes with `anyOf`. Unhandled server errors have
no declared JSON domain contract.
