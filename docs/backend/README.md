# Backend documentation

## HTTP API: the central reference

Start the backend and open `http://<backend-host>:<backend-port>/docs`.
Swagger UI describes all 27 HTTP operations, grouped by Projects, Project Git,
Tasks, AI Providers, Agent Executions and Status. `/docs/json` provides the
OpenAPI 3.0.3 specification. ΓÇ£Try it outΓÇ¥ targets the backend origin serving the
portal.

Route schemas and shared public response schemas are the source of truth for
HTTP contracts. Update them alongside endpoint changes.

## Architecture and flows

- [OpenAPI setup and maintenance](openapi.md).
- [AsyncAPI structure and toolchain](asyncapi.md).
- [WebSocket connection, lifecycle and recovery](websocket-guide.md).
- [Project registration, cloning and task events](project-registration.md).
- [Project listing](project-listing.md).
- [Project synchronization](project-sync.md).
- [Git branches, history and checkout](project-branches.md).
- [Checkout file previews](project-files.md).
- [AI providers, models and credentials](ai-providers.md).
- [Agent execution lifecycle and WebSocket events](agent-execution.md).

These Markdown documents explain behavior and system flows; consult Swagger for
the current HTTP request/response definitions. WebSocket event contracts are
generated separately as AsyncAPI from shared TypeScript schemas and are not
included in OpenAPI; Markdown describes their connection and recovery flows.

## Automated verification

The OpenAPI integration test validates the generated specification and compares
its exact methods/paths against the baseline defined in the test. The endpoint integration
suites audit serialized responses for field loss.
