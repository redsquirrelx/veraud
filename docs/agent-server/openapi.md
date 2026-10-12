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
- Exact method/path coverage against both registered routes and the initial
  inventory, including metadata and unique operation IDs.
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
2. Update the inventory method/path baseline when adding, removing or renaming
   an operation. Its other findings remain the initial snapshot.
3. Add representative contract cases when introducing new response behavior.
4. Keep examples consistent with registered agents and supported providers.
5. Run the tests, Ruff and `git diff --check`.

The generated `/openapi.json` is ready to be consumed by a future backend portal
service selector. Do not maintain a duplicate static specification. The backend
retains its separate OpenAPI 3.0.3 document at `/docs/json`.

## Verification record

The completed integration was checked through TestClient and HTTP against an
isolated local server, with no browser installation. A rendered visual review
or click on Swagger's ΓÇ£Try it outΓÇ¥ was not performed; relative URL resolution
and the target status endpoint were verified over HTTP instead.

- Full `tests/` suite: **33 tests passed**, including the 10 existing analyzer tests.
- Ruff on the API, application entry point and new contract tests: passed.
- `git diff --check`: passed.
- `/docs`, `/redoc`, `/openapi.json` on a temporary HTTP server: 200.
- Status URL resolved to that server's actual host/port: 200 with the expected JSON.
- Temporary HTTP server stopped after verification.
