# Backend AsyncAPI setup

## Overview

Shared TypeScript contracts generate the WebSocket specification. The YAML contains
three message definitions, two reusable payload schemas and six examples.
Connection/delivery/recovery guidance is embedded in the generated document and
in [the WebSocket usage guide](websocket-guide.md). The backend now serves the
portal at `/docs/ws` and generated YAML at `/docs/ws/spec`.

See [the WebSocket usage guide](websocket-guide.md) for current wire behavior,
delivery limitations and lifecycle discrepancies.

## Specification structure

The authored sources are:

- `backend/src/infrastructure/realtime-gateway/eventCatalog.ts`: event
  envelopes, discriminators, operation IDs, summaries, tags and typed examples.
- `backend/src/infrastructure/realtime-gateway/eventPayloadSchemas.ts`: shared
  task and execution payload schemas, each defined once.
- `backend/src/infrastructure/realtime-gateway/eventSchemaTypes.ts`: schema-based
  type helpers for JSON wire values and existing producer values.
- `backend/src/infrastructure/asyncapi/asyncApiMetadata.ts`: explicit connection
  and document metadata.
- `backend/src/infrastructure/asyncapi/buildAsyncApiDocument.ts`: pure builder
  which derives operations from the catalog and rejects duplicate event types
  or operation IDs.

`backend/src/infrastructure/asyncapi/asyncapi.yaml` is generated and versioned.
Do not edit it manually. Make authored changes in the TypeScript sources and run
the generation command. TypeScript interfaces are not inspected at runtime to
produce the document.

- AsyncAPI **3.1.0**: accepted by the selected parser and renderer. This is
  independent of the backend's OpenAPI 3.0.3 specification.
- Application title: **Veraud Backend WebSocket API**; API version `1.0.0`.
- Stable application ID: `urn:veraud:backend:websocket`.
- Default content type: `application/json`, describing JSON text payloads,
  not an extra header sent with each WebSocket frame.
- One channel ID, `realtime`, with address `/ws`.
- WebSocket channel binding version **0.1.0**, handshake method **GET**.
- No required query/header schemas, security schemes or subprotocol are added,
  because none are declared by the current application.

Operations use the **backend's perspective**:

| Operation ID | Action | Message |
| --- | --- | --- |
| `sendTaskUpdated` | `send` | `task.updated` |
| `sendAgentExecutionOpened` | `send` | `agent-execution.opened` |
| `sendAgentExecutionUpdated` | `send` | `agent-execution.updated` |

There is no backend-receive operation: the gateway has no application client
message handler. Each operation shares the same physical channel; separate
operations do not imply separate sockets or subscriptions.

The builder creates `components.messages`, `components.schemas`, channel message
references, and operation message references. Operation message references
point to `#/channels/realtime/messages/...`, not directly to component messages.
The full envelope, including its type discriminator, belongs in each payload
schema so the three messages remain distinguishable. The task payload needs its
own schema; the HTTP Task schema includes repository names absent from the wire.

## Connection addresses

The development server uses protocol `ws` with parameterized host
`{hostname}:{port}`, defaulting to `localhost:7501`. The channel supplies `/ws`,
so the path must not be duplicated in the server pathname.

These are editable development examples, not automatic origin discovery. For a
TLS-terminated deployment, use `wss` and the external host/port. The document
does not claim this route configures TLS. The portal shows the current backend's
connection address separately from these defaults.

## Selected tools

| Purpose | Tool/version | Integration status |
| --- | --- | --- |
| Parse and validate YAML/AsyncAPI | `@asyncapi/parser` **3.6.3** | Exact backend development dependency |
| Derive types from JSON Schema | `json-schema-to-ts` **3.1.1** | Exact backend development dependency; type-only imports |
| Read/write generated YAML | `yaml` **2.9.1** | Exact backend development dependency |
| Render documentation | `@asyncapi/react-component` **3.2.1** | Exact backend dependency; its standalone bundle and styles are served locally |
| Renderer React runtime | React/ReactDOM **18.3.1** | Exact backend dependencies; included in the standalone bundle, isolated from the frontend's React 19 |

The official HTML template 3.5.6 supports parser API v3, but includes Puppeteer
as a dependency. The chosen route uses the official component directly and
requires no browser automation package, PDF tooling or downloaded browser.

The portal uses static HTML and locally served component/runtime/style assets.
The standalone official bundle includes React and its browser-side AsyncAPI
parser. It renders the exact YAML returned by `/docs/ws/spec`. Documentation
requests do not install dependencies, fetch CDN resources or parse AsyncAPI on
the backend. The browser parses the document as part of rendering it.

Validation runs from `backend/`:

```bash
pnpm run docs:ws:validate
```

The entry point is `src/infrastructure/asyncapi/validateAsyncApi.ts`. It reports
parser diagnostics and exits unsuccessfully if parsing fails or an error-level
diagnostic exists. The current document validates with zero diagnostics,
one channel and three operations.

The transitive `@scarf/scarf` install script is explicitly disabled in the
backend's existing pnpm build policy.

## Shared schema and generation design

Declare JSON Schemas as TypeScript values with `as const` and `satisfies
JSONSchema`. Derive types using `WirePayload<typeof schema>` rather than
duplicating payload interfaces. `ProducerPayload<typeof schema>` maps
`type: string, format: date-time` to Date for the existing emitters, while
WirePayload keeps those fields as strings. Nullable date fields remain nullable
in both representations. This is type inference only: it does not coerce,
validate or filter messages at runtime. JSON.stringify retains its existing role.

The gateway exports TaskEvent, AgentExecutionEvent and GatewayEvent derived from
the catalog, so existing emitter signatures share the schema-based definitions.
GatewayWireEvent describes their JSON representation. Common payload schemas
carry IDs for type inference; the document builder turns those references into
document-local component references and removes the schema IDs in the generated
components. This avoids changing reference resolution inside the AsyncAPI document.

Task fields deliberately omit HTTP-only repository names. Agent result remains
an opaque nullable string, and all emitted nullable fields remain required in
the wire schema. Status/kind stay strings with described lifecycle values, rather
than introducing new runtime enum restrictions. Event discriminators use const.
Schemas disallow extra wire fields to make drift detectable in contract checks;
the production gateway still sends JSON.stringify output without filtering or
runtime validation.

Available commands, from `backend/`:

| Command | Responsibility | Status |
| --- | --- | --- |
| `docs:ws:generate` | Deterministically write YAML from the builder, with a generated-file notice | Available |
| `docs:ws:validate` | Validate the resulting YAML independently with the parser | Available |
| `docs:ws:check` | Compare the versioned YAML against generated output without writing files | Available |

```bash
pnpm run docs:ws:generate
pnpm run docs:ws:validate
pnpm run docs:ws:check
```

The check fails for a missing or stale file and tolerates Git's CRLF/LF checkout
differences. It does not write the YAML. Generation uses
`serializeAsyncApi.ts`; filesystem entry points are `generateAsyncApi.ts` and
`checkAsyncApi.ts`.

The builder performs no filesystem access or environment reads. Generation
uses a fixed serializer configuration and no timestamps, so unchanged authored
contracts yield unchanged output. The portal and downloadable specification
consume that same output. Real-message tests remain necessary even with
shared definitions: TypeScript alone does not validate emitted values at runtime.

## Portal paths

```text
/docs                  → existing Swagger UI
/docs/json             → existing OpenAPI JSON
/docs/ws               → AsyncAPI portal (also served at /docs/ws/)
/docs/ws/spec          → generated AsyncAPI YAML
/docs/ws/assets/...    → local portal scripts/styles and bundle license notice
```

The new documentation routes are hidden from OpenAPI, just like `/ws`, and are
registered by `registerAsyncApi` in `buildApp`. The Swagger description links to
the WebSocket portal, and the WebSocket portal links back to Swagger.

## Serving and preparing the portal

`loadPortalResources.ts` reads the generated YAML and static HTML when an application
is built and caches local assets per process. `registerAsyncApi.ts` registers the
documentation routes. Responses use explicit
HTML/YAML/JavaScript/CSS content types and no-cache headers. Assets are served
from an explicit route list rather than an unrestricted filesystem path.

The portal shows the current page origin converted to ws/wss with path `/ws`.
This address is separate from the editable development defaults in the document;
the portal does not open a WebSocket connection. It provides a YAML download,
loading/error feedback and a JavaScript-disabled download path.

`pnpm run dev` runs `predev`, which executes:

```bash
pnpm run docs:ws:prepare
```

This generates, validates and checks synchronization before starting the backend.
After editing contracts or metadata during development, run prepare again and
restart the backend to refresh the startup-loaded spec. Test commands that
directly build the application read the checked-in generated YAML.

For deployment, run prepare with development dependencies installed before
packaging. Include `asyncapi.yaml`, the `portal/` files and the runtime renderer
dependency alongside the backend. The current backend runs from TypeScript;
if introducing a compiled build, copy those non-TypeScript resources next to
the compiled registration module. Production requests do not need generation
or validation dependencies.

## Automated verification

`registerAsyncApi.test.ts` checks portal HTML, the exact generated specification,
local assets and JavaScript syntax, Swagger coexistence and exclusion from
OpenAPI. Bootstrap checks use a Node VM with small mocked DOM/render functions,
covering same-origin specification loading, ws/wss addresses and HTTP errors.
They do not constitute a browser visual review or execution of the full renderer
in a browser.

Run the portal and HTTP documentation checks from `backend/`:

```bash
pnpm exec tsx --test src/infrastructure/asyncapi/registerAsyncApi.test.ts src/tests/openapi.integration.test.ts
pnpm run docs:ws:check
pnpm run docs:ws:validate
```

## References

- [AsyncAPI 3.1.0 specification](https://www.asyncapi.com/docs/reference/specification/v3.1.0).
- [WebSocket bindings](https://github.com/asyncapi/bindings/blob/master/websockets/README.md).
- [Official React component](https://github.com/asyncapi/asyncapi-react).
