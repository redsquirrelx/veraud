# Agent-server HTTP endpoint inventory

Step 1 of the agent-server Swagger plan. Snapshot reviewed on 2026-10-11.
This records current behavior and documentation gaps before changing route
metadata or models.

## Sources and scope

- `agent-server/src/server/main.py`: application and status route.
- `agent-server/src/server/api/executions.py`: agent routes and error mapping.
- `agent-server/src/server/api/schemas.py`: HTTP request and response models.
- `agent-server/src/server/app/execution_service.py`: configuration resolution,
  agent validation, execution, timeout and callbacks.
- `agent-server/src/server/app/agent_registry.py`: registered-agent lookup.
- `agent-server/src/server/agents/{dummy,analyzer}/schemas.py`: agent contracts.
- `agent-server/config/dev-agents.yaml`: current base configuration.
- `agent-server/src/server/infrastructure/callback/client.py`: outgoing callbacks.

There are four application HTTP operations. FastAPI also serves `/docs`,
`/docs/oauth2-redirect`, `/redoc` and `/openapi.json`; these framework documentation
routes are not application operations. The reviewed routers declare no
authentication dependency or WebSocket endpoint.

## Operations

| Method | Path | Request | Successful response | Expected errors |
| --- | --- | --- | --- | --- |
| GET | `/api/status` | None | `200`, `{"status":"ok","service":"agent-server"}` | No explicit domain errors |
| GET | `/api/agents` | None | `200`, sorted array of registered agent names; currently `["analyzer","dummy"]` | No explicit domain errors |
| GET | `/api/agents/{agent_type}/schema` | Required string path parameter | `200`, `AgentSchemaResponse` | `404` unknown agent; framework validation `422` is advertised |
| POST | `/api/agents/run` | Required JSON `ExecutionRequest` | `200`, `ExecutionResponse` after execution completes | `404` unknown agent; `422` request validation, invalid configuration, invalid agent input or missing file; `504` timeout |

The status route has no response model or return annotation. The other three
routes explicitly declare response models. No route uses a non-default success
status. Unhandled exceptions can produce server errors; these do not currently
have a declared JSON domain contract.

## HTTP models and validation

### ExecutionRequest

| Field | Type | Required/default | Current validation or behavior |
| --- | --- | --- | --- |
| `agent_type` | string | Required | No enum or minimum length; service resolves it against the registry |
| `config` | ExecutionConfig | Omitted creates a default instance | Explicit `null` is not accepted |
| `input` | object | Omitted creates `{}` | Arbitrary keys at HTTP level; validated against the chosen agent's model by the service |
| `execution_id` | integer or null | Default `null` | Minimum 1 when provided; enables callback reporting when backend configuration is available |

### ExecutionConfig and ModelConfig

`config.model` is a non-null ModelConfig object, created when omitted. Its fields
`provider`, `name`, `temperature` and `max_tokens` are all optional and nullable,
with default `null`. Their types are string, string, number and integer,
respectively.

`config.timeout_seconds` is an optional nullable integer and `config.api_key` is
an optional nullable string, both defaulting to `null`. The wire models declare
no positive timeout constraint, provider enum, temperature range or token limit.
The service checks timeout positivity separately.

These Pydantic models use default, non-strict behavior and do not forbid extra
fields. Unknown model fields are ignored rather than rejected. Documentation
must describe current behavior without introducing stricter validation.

### Responses

- `ExecutionResponse`: required `agent_type` string and `result` object. The
  result is built from the agent output's `model_dump()` and returned through
  FastAPI serialization. It is not a job acknowledgement or execution ID.
- `AgentSchemaResponse`: required `agent_type` string, `input_schema` object and
  `output_schema` object. The two schemas come from the selected agent's Pydantic
  `model_json_schema()`; nested `$defs` belong to those returned schema documents.
- `/api/agents`: array of strings, alphabetically sorted by the registry.

## Configuration resolution and execution

1. Resolve the registered agent first; unknown names raise `UnknownAgentError`.
2. Merge request overrides with `config/dev-agents.yaml`.
3. Build the model client and agent.
4. Validate `input` with the agent's input model.
5. Optionally report running status, await the agent with a timeout, report its
   outcome, and return the output.

Resolution rules:

- `provider`: truthy request value, otherwise base provider, otherwise `gemini`.
- `name`: truthy request value, otherwise base name; a missing/empty resolved
  name raises `InvalidConfigError`.
- `temperature`: request value unless `null`, otherwise base value or `0.2`.
- `max_tokens`: request value unless `null`, otherwise base value or `1000`.
- `timeout_seconds`: request value unless `null`, otherwise base value or `60`;
  zero and negative values raise `InvalidConfigError`.
- `api_key`: truthy request value or server key. A settings `ValidationError`
  during that lookup falls back to `dev-dummy-key`.
- Supported provider names are `gemini`/`google` and `openrouter`/`openai`;
  provider matching is case-insensitive. Other names raise `InvalidConfigError`.

Empty strings for provider, name and API key follow the truthy fallback rules;
numeric zero for temperature or max_tokens is not replaced by a default.
The timeout wraps the agent run, not the entire HTTP operation or callback
delivery. Configuration errors can occur before agent input validation.

## Per-agent contracts

| Agent | Input | Output |
| --- | --- | --- |
| `dummy` | Required `code` string; `evaluated_attribute` defaults to `maintainability` | Required `evaluated_attribute` and score in 0ΓÇô100; findings and recommendations default to empty arrays |
| `analyzer` | Required `root_path` string; `max_files=500`, `max_depth=8`, `max_read_rounds=2`, `max_files_per_round=8` | ProjectDescription with required `kind`, `summary`, `primary_language`; defaulted lists and evidence fields |

Analyzer input requires `max_files`, `max_depth` and `max_files_per_round` to be
at least 1, and `max_read_rounds` at least 0. Its output `kind` is one of `cli`,
`library`, `web_service`, `desktop_app`, `data_pipeline`, `script`, `unknown`.
`confidence` is `low`, `medium` or `high`, defaulting to `low`; `files_read` and
`read_rounds` default to 0 and must be nonnegative; `hypothesis_confirmed`
defaults to false. `entrypoints` and `key_components` default to empty arrays.
Dummy findings require title and description; severity defaults to `low` but
is a plain string, not an enforced enum.

## Errors

Domain errors use `{"detail":"..."}` via HTTPException:

- `404`: unknown agent on schema lookup or execution. UnknownAgentError extends
  KeyError, so its current string representation includes outer quotation marks;
  preserve that existing message formatting.
- `422`: InvalidConfigError, InvalidInputError or FileNotFoundError on execution.
  Input errors contain the agent name and Pydantic validation text.
- `504`: fixed detail `Agent execution timed out`.

Framework request validation uses `{"detail":[...]}` with items such as `loc`,
`msg`, `type`, and, depending on the failure, `input` and `ctx`. These fields
must not be confused with the string detail used for domain failures. A future
documented `422` response must describe both shapes.

## Outgoing callbacks

Callbacks target backend operations; they are not additional agent-server
endpoints:

- `POST /api/agent-executions/{execution_id}/running` with `{}`.
- `POST /api/agent-executions/{execution_id}/completion` with a Completed outcome
  containing a JSON-string result, or a Failed outcome containing an error.

The destination is `http://localhost:<PORT_BACKEND>`. If there is no execution ID
or backend settings are unavailable, reporting is skipped. Transport failures
and rejected callback responses are returned as unacknowledged results by the
callback client rather than failing the run. Input/configuration failures happen
before the execution reporting block. The HTTP execution response contains a
nested result object, whereas completion callbacks carry a serialized string.

## Current OpenAPI and documentation gaps

Observed specification: OpenAPI **3.1.0**, title **FastAPI**, version **0.1.0**.
Keep its version distinct from the backend's OpenAPI 3.0.3 and from package
version `0.0.0` when deciding portal metadata in step 2.

- All four application operations are discovered.
- Agent operations use tag `agents`; status is untagged.
- FastAPI generates summaries and operation IDs; schema and run operations also
  have descriptions from docstrings, but metadata is not consistently curated.
- Status advertises `200` with an unconstrained response schema.
- Agent list advertises `200`; schema and run advertise `200` and framework `422`.
- Domain `404` and `504` are absent. The advertised `422` only describes
  HTTPValidationError, not string-detail domain errors.
- Components already include AgentSchemaResponse, ExecutionConfig,
  ExecutionRequest, ExecutionResponse, ModelConfig, HTTPValidationError and
  ValidationError.
- Missing field descriptions, request examples, per-agent usage guidance,
  service default/fallback explanations and callback lifecycle guidance need
  completion in later steps.
- No shared status or domain-error model exists yet.

### Configuration discrepancies

The current YAML assigns provider `groq` to both registered agents, but
`build_model()` does not support it. A dummy run with valid input and no provider
override currently returns `422` with detail `Unsupported model provider: 'groq'`.
Examples that omit overrides must account for this rather than promise success.

The YAML also contains `architect`, which is not in the default registry.
It is absent from `/api/agents` and its schema lookup returns `404`.
These are recorded findings; correcting configuration or provider support is
outside this inventory step.

## Existing tests and verification

`tests/test_analyzer_determinism.py` contains 10 deterministic analyzer tests;
they passed using the existing virtual environment. They exercise derived facts
and parsing, not HTTP or OpenAPI contracts. `src/server/test_agent.py` is a
manual development runner rather than HTTP contract coverage. No TestClient
tests were found in the reviewed Python sources.

Additional in-process checks used the installed FastAPI TestClient and existing
virtual environment, with no browser installation:

- `/docs`, `/redoc`, `/openapi.json`: HTTP 200.
- `/api/status`: HTTP 200 with the two expected fields.
- `/api/agents`: HTTP 200 with `["analyzer","dummy"]`.
- Schema lookup for dummy and analyzer: HTTP 200; architect: HTTP 404.
- Run with missing agent_type or execution_id=0: framework HTTP 422.
- Run with an unknown agent: domain HTTP 404.
- Dummy run with valid input and current defaults: domain HTTP 422 for groq.
- Default ExecutionRequest values and generated operation responses were inspected.

No successful LLM run, timeout simulation, file-error simulation, or complete
serialization audit was performed in this inventory step. Those contract checks
belong to step 6 and should use substituted dependencies. Application code,
runtime validation and response serialization were not changed by step 1.
