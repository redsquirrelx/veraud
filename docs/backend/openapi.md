# Backend OpenAPI portal

The backend serves Swagger UI at `/docs` and its generated OpenAPI 3.0.3
specification at `/docs/json`. Use the backend host and port, rather than the
React frontend URL.

```text
http://<backend>/docs
http://<backend>/docs/json
```

Configuration lives in
`backend/src/infrastructure/openapi/registerOpenApi.ts` and is registered in
`buildApp` before application controllers. The plugins are `@fastify/swagger`
9.x and `@fastify/swagger-ui` 6.x, compatible with Fastify 5.

The portal discovers routes and their existing Fastify schemas. Shared response
contracts are registered by `registerApiSchemas.ts` in the root application
scope, before controllers. Definitions are grouped under `openapi/schemas/`:

- `projects.ts`: ProjectSummary and RegisteredProject.
- `agentExecutions.ts`: AgentExecution and VersionAnalysis.
- `aiProviders.ts`: AiModel, AiCredential and AiProvider.
- `tasks.ts`: the HTTP Task representation.
- `errors.ts`: MessageError, ExecutionError and ValidationError.

References use `$ref: "SchemaId#"`. Required nullable fields are represented
with JSON Schema null unions; Swagger converts these to OpenAPI 3.0-compatible
schemas. Dates describe their ISO HTTP representation. Public response schemas
omit internal database fields, including full API keys.

All 30 explicit backend HTTP operations now reference response contracts and
include tags, summaries and descriptions. Input examples and service-level
validation/default descriptions live alongside the route schemas. Response
schemas participate in Fastify serialization; the existing integration tests
verify the public responses.

`400` responses distinguish Fastify validation errors from domain errors through
`anyOf` where necessary. Domain errors retain their existing `{ message }` or
`{ error }` shapes. DELETE success is documented as `204` without content.
Input defaults and trimming-sensitive constraints are described rather than
added as new validation rules, preserving current service behavior.

The endpoint integration suites compare controller payloads with emitted HTTP
JSON through test-only serialization hooks to detect field loss or value changes.
`/docs` is the current HTTP contract reference. See also
[the documentation index](README.md).

The portal documents backend HTTP operations. WebSocket event contracts are
published separately at `/docs/ws`; see [the AsyncAPI guide](asyncapi.md).

## Portal organization

The seven groups appear in this order: Projects, Project Git, Tasks, AI Providers,
Agent Executions, Agent Settings and Status. Each has a description. Groups start collapsed,
operations are ordered alphabetically, and the UI enables filtering, deep links
and request-duration display.

The OpenAPI server URL is `/`, so requests use the current backend origin
instead of a fixed development port or the React frontend origin.

## Maintaining coverage

`src/tests/openapi.integration.test.ts` validates `/docs/json` with
`@apidevtools/swagger-parser`, including OpenAPI structure and schema references,
and compares the exact HTTP methods and paths against a baseline defined in the test.
It checks operation metadata, successful responses, empty DELETE contracts and
representative domain/validation error shapes.

When adding or changing a route:

1. Update its schema, operation description and examples in the controller.
2. Update shared response schemas when a public structure changes.
3. Update the test's method/path baseline if a route is added, removed or renamed.
4. Run `pnpm test`, `pnpm exec tsc --noEmit` and `pnpm run lint` from `backend/`.
5. Review the resulting operation in `/docs`.

Keep Markdown focused on flows and architecture; avoid separately maintaining
an OpenAPI file that can drift from the route schemas.

The root README and backend documentation index link to the portal; flow
documents point readers there for the current HTTP contracts.
