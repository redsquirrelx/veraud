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

All 27 explicit backend HTTP operations now reference response contracts and
include tags, summaries and descriptions. Input examples and service-level
validation/default descriptions live alongside the route schemas. Response
schemas participate in Fastify serialization; the existing integration tests
verify the public responses.

`400` responses distinguish Fastify validation errors from domain errors through
`anyOf` where necessary. Domain errors retain their existing `{ message }` or
`{ error }` shapes. DELETE success is documented as `204` without content.
Input defaults and trimming-sensitive constraints are described rather than
added as new validation rules, preserving current service behavior.

The [serialization review](response-serialization-review.md) compares actual
controller payloads with emitted HTTP JSON through test-only hooks, covering
the existing endpoint integration suites. The review detected no field loss
or value changes in exercised responses.
The [endpoint inventory](http-endpoint-inventory.md) records the initial audit
and is used as the method/path coverage baseline; `/docs` is the current HTTP
contract reference. See also [the documentation index](README.md).

The portal documents the backend only. WebSocket event contracts remain in
the existing Markdown documentation.

## Portal organization

The six groups appear in this order: Projects, Project Git, Tasks, AI Providers,
Agent Executions and Status. Each has a description. Groups start collapsed,
operations are ordered alphabetically, and the UI enables filtering, deep links
and request-duration display.

The OpenAPI server URL is `/`, so requests use the current backend origin
instead of a fixed development port or the React frontend origin.

## Step 6 verification

The portal HTML, CSS, generated specification and Swagger initializer were
checked on an isolated backend instance with a temporary database. All six tags,
11 shared schemas and configured UI settings were present. Resolving the server
URL from that portal origin and requesting `/status` returned HTTP 200 with the
expected backend payload.

The six groups and project-registration example were also checked in the UI.
ΓÇ£Try it outΓÇ¥ ΓåÆ GET /status ΓåÆ ΓÇ£ExecuteΓÇ¥ sent a request to the backend's actual
host/port and returned HTTP 200 with the expected JSON. No JavaScript page errors
were observed during that check. The detailed visual inspection of expanded
nested models was not completed; their references and nullable representations
are covered by automated schema/OpenAPI validation instead.

## Maintaining coverage

`src/tests/openapi.integration.test.ts` validates `/docs/json` with
`@apidevtools/swagger-parser`, including OpenAPI structure and schema references,
and compares the exact HTTP methods and paths against the endpoint inventory.
It checks operation metadata, successful responses, empty DELETE contracts and
representative domain/validation error shapes.

When adding or changing a route:

1. Update its schema, operation description and examples in the controller.
2. Update shared response schemas when a public structure changes.
3. Update the inventory baseline if a method/path is added, removed or renamed.
4. Run `pnpm test`, `pnpm exec tsc --noEmit` and `pnpm run lint` from `backend/`.
5. Review the resulting operation in `/docs`.

Keep Markdown focused on flows and architecture; avoid separately maintaining
an OpenAPI file that can drift from the route schemas.

## Final verification

- `/docs` HTML and static assets: checked.
- `/docs/json`: validated against OpenAPI with all schema references resolved.
- Exact inventory coverage: all 27 HTTP methods/paths checked.
- Groups, metadata, successful responses and empty DELETE contracts: checked.
- Representative validation and domain errors: checked.
- Full backend suite: 156 tests passed.
- TypeScript, lint and whitespace checks: passed.

The root README and backend documentation index link to the portal; flow
documents point readers there for the current HTTP contracts.
