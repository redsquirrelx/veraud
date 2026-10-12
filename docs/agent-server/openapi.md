# Agent-server OpenAPI portal

FastAPI serves Swagger UI at `/docs`, ReDoc at `/redoc`, and the generated
OpenAPI 3.1.0 document at `/openapi.json`. The application title is
**Veraud Agent Server API**, version `0.0.0`, matching `pyproject.toml`.

## Implementation

- `src/server/main.py`: metadata, described Status/Agents groups, Swagger UI
  configuration and status operation.
- `src/server/api/executions.py`: operation descriptions, request examples,
  success responses and domain errors.
- `src/server/api/schemas.py`: public Pydantic models, defaults, descriptions
  and examples.
- Agent-owned input/output models are published dynamically through
  `/api/agents/{agent_type}/schema`; the run endpoint stays agent-agnostic.

Swagger groups start collapsed. Filtering, deep links, request duration and
alphabetical operation sorting are enabled. The spec URL is relative and there
is no hardcoded server host/port, so requests resolve against the portal origin.

DomainError represents string-detail domain failures. RequestValidationErrorResponse
describes FastAPI's list-detail failures without replacing its exception handler.
The execution route advertises their union for `422`. Additional error models
are documentation metadata, not new runtime validation of error responses.
StatusResponse explicitly describes the existing two-field status response.

See [the usage guide](execution-guide.md) for configuration and callback flows.

## Automated verification

`tests/test_openapi_contracts.py` uses FastAPI TestClient with substituted
execution dependencies and tracing disabled. It makes no model or callback
network calls. It checks:

- Portal URLs, metadata and Swagger settings.
- OpenAPI structure and references using `openapi-spec-validator`.
- Exact method/path coverage against registered routes and the baseline in the
  test, including metadata and unique operation IDs.
- Documented response examples and actual response payloads against JSON Schema.
- Named dummy/analyzer request examples against the selected agent's input schema.
- Published agent schemas against their Pydantic models.
- Successful status/list/schema/execution responses, including nested, nullable
  and arbitrary result data, to detect serialization field loss.
- Both `422` variants, unknown-agent `404`, missing-file failures and timeout
  `504` through substituted service failures.
- Defaults, nullable overrides, service fallback values and input validation.

The existing analyzer determinism tests remain part of the suite. The contract
checks exercise representative data; they do not execute real providers or
simulate every possible value returned by an agent.

From `agent-server/`:

```bash
uv sync
uv run pytest tests -q
uv run ruff check src/server/main.py src/server/api tests/test_openapi_contracts.py
```

The specification validator is a development dependency. No browser automation
dependency is needed.

## Maintenance

1. Update route metadata and Pydantic models alongside HTTP changes.
2. Update the method/path baseline in `tests/test_openapi_contracts.py` when
   adding, removing or renaming an operation.
3. Add representative contract cases when introducing new response behavior.
4. Keep examples consistent with registered agents and supported providers.
5. Run the tests, Ruff and `git diff --check`.

The generated `/openapi.json` is ready to be consumed by a future backend portal
service selector. Do not maintain a duplicate static specification. The backend
retains its separate OpenAPI 3.0.3 document at `/docs/json`.
