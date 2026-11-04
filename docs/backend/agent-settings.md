# Discovered agents and saved configuration

`GET /api/agent-settings` lists the agents declared by the last successfully
synchronized agent-server catalog and their saved `AgentSettings`. Swagger describes
the response under **Agent Settings** at `/docs`.

## Source of available agents

Agent-server `GET /api/agents/catalog` is the source of truth. The backend uses
the canonical `agent_id` as `agentType` and stores its published `name`, `role`,
model requirements, execution modes and availability. Backend workflow constants
in `agent-types.ts` are transport identifiers, not a registration allowlist.
Adding an agent to the server catalog does not require a backend seed change.
Quality-audit model participant expansion also traverses the synchronized hierarchy
and its `modelConfigurationAgentType` values, rather than a backend investigator list.
It retains the existing per-attribute root model selection policy.

## Automatic synchronization

When `agentServerUrl` is configured, startup fetches the catalog with a five-second
timeout. It validates version `1.0`, unique identities, model configuration owners,
parent/child reference consistency and absence of cycles **before** writing.
One database transaction creates missing rows and updates metadata and links.
Existing model/credential assignments, generation options, verification records
and execution history are preserved. Repeating synchronization is idempotent.

Each declared agent gets a row, including deterministic/internal participants.
No model or credential is selected automatically. Agents removed from the catalog
are marked `catalogDeclared: false`, excluded from settings and rejected for new
assignments/executions. Their rows and historical execution references remain.
Legacy rows become active only if their canonical ID is declared by the server.

On an unavailable service, unsupported version or malformed graph, the last
successful catalog is retained. A fresh installation without discovery has an
empty agent list; there is no hard-coded fallback. Listing uses the persisted
catalog and does not contact agent-server. Retry after starting agent-server with:

```http
POST /api/agent-settings/sync
```

Success returns the synchronized settings list. Unavailable/unconfigured discovery
or invalid catalog returns `503` without partially updating the database.
`BuildAppOptions.makeAgentCatalogSource` injects discovery in isolated tests.

## Optional hierarchy

Migration `20261018000000_agent_server_catalog` adds catalog metadata and the
`agent_hierarchy` self-relation table. Each link references a parent and child
`agent_settings.agent_type`; a composite key prevents duplicate links. An agent
can have no children, several children, or multiple parents without duplicating
its configuration row. The catalog graph is validated against self-links/cycles.
Each successful sync replaces links with the current declared graph.

Settings responses include `parentAgentTypes` and `childAgentTypes` arrays (empty
when absent), `name`, `role`, `requiresModel`, `modelConfigurationAgentType`,
`executionModes` and `availability`. A model-independent agent such as
`audit_report` requires no assignment. A participant sharing another agent's
model, such as `remediation_synthesizer` using `security`, is configured through
that owner. PUT/verify reject participants without an available independent model.

## Quality and workflow context for clients

Agent-server declares `quality_attributes` and `workflow_ids` on every catalog
entry. The backend validates both as lists of unique nonempty strings and persists
them without deriving membership from names, roles or parents. The public settings
response (GET, synchronization, save and verification) exposes camel-case fields:

```json
{
  "agentType": "audit_report",
  "qualityAttributes": ["maintainability", "security"],
  "workflowIds": ["quality-audit"]
}
```

The example shows the contextual portion of a settings record. Frontend
`AgentSettings` types include both arrays, ready for filtering/grouping. An agent
may support several attributes; an empty quality list does not mean security or
maintainability by default. Project analysis stages use `workflowIds` to identify
`project-architecture`; functional adequacy declares `functional_adequacy`.
These are declared capabilities, not the selected attributes or actual participants
of a specific run. Availability remains separate (DAST is still `not_executed`).

Migration `20261018010000_agent_execution_context` adds JSON-array columns with
empty defaults. Existing settings/verification/history survive. Restart agent-server
and backend and synchronize to populate real context; no legacy membership is
invented. Updated discovery requires both context fields, so an older server response
is rejected and the last synchronized catalog is retained. The catalog remains
version `1.0` with additive descriptor metadata. Offline reads retain saved context.

## Saved settings

`agent-settings.repository.ts` queries the existing Prisma `AgentSettings` model
and its model, credential and provider relations. It returns model and credential
IDs/names/provider information, temperature and maximum tokens. List queries never
select the credential's API key. Internal access checks and dispatch read the key
and send it only to the agent-server, never to the browser or WebSocket clients.

The service returns each `agentType` with nullable `configuration` and a
`configured` boolean. That boolean means a saved model/credential pair exists
and belongs to the same provider; it does not verify access against the provider.

## Frontend

Settings loads this endpoint when the **Agents** tab is opened. It renders one
Card per returned agent, with configured/pending status and editable model and
credential selectors. Credentials remain disabled until a model is selected and
are filtered by its provider. Changing providers clears the selected credential;
changing models within the same provider retains it. **Save changes** persists
the pair and updates the Card with the returned configuration. Controls are
disabled during saving, and failed saves retain selections for retry.
**Configure** opens an editable Drawer with model/credential selection and
generation parameters. Temperature accepts values from 0 to 2; maximum tokens
accepts positive integers up to 2147483647. Empty fields clear the stored override
to null. Saving updates the Card, closes the Drawer and shows a success toast
after backend confirmation. Cancel discards unsaved Drawer edits.
Clients can use `requiresModel`, `modelConfigurationAgentType` and `availability`
to distinguish independent model settings from deterministic/shared participants,
and `parentAgentTypes`/`childAgentTypes` to present the hierarchy.
Loading, empty-list and retryable error states are supported. Requests are
cancelled when the section unmounts.

## Saving assignments

`PUT /api/agent-settings/:agentType` accepts:

```json
{ "modelId": 1, "credentialId": 2, "temperature": 0.5, "maxTokens": 4096 }
```

The backend validates that both records exist and share a provider, then saves
the assignments transactionally. Temperature and maximum tokens are optional:
omitting them preserves saved values, while sending null clears them. Invalid
ranges and non-integer maximum tokens return `400`.
The response is the updated agent configuration without API keys. Undeclared
types return `404`, invalid assignments return `422`, and malformed bodies return
`400`. Swagger documents the operation under **Agent Settings**.

## Model access and execution configuration

`POST /api/agent-settings/:agentType/verify` checks the saved model and credential
through `POST /api/agents/verify-access` on the agent-server. The probe performs a
minimal generation request (which may incur provider usage), requires explicit
provider/model/key and never falls back to the server key. Verification timeouts
are 25 seconds on the agent-server and 30 seconds on the backend.

Settings responses include `verification: { status, checkedAt, message }`:
`not_verified`, `verified` or `failed`. The UI displays **Not verified**,
**Verified** or **Needs attention** in Cards and Drawers. A failed provider check
returns the saved settings with `failed`; an incomplete configuration returns
`422`. Provider error bodies are replaced by controlled messages.

Model name edits and API-key changes increment revisions; changes to assignments
or generation parameters also invalidate previous checks. A verification result
is recorded only if the configuration still matches the checked version.

Every backend execution start repeats the live access check, including previously
verified pairs, so revoked keys are not trusted based on an old success. Missing
assignments, mismatched providers, invalid generation parameters and denied access
block the start with `422`, including `agents: [{ agentType, reason }]`.
`prepareExecution(agentTypes)` checks all required types and collects their issues
before a workflow creates any records. Project analysis requires
`orientation`, `architecture` and `semantic_validation`, each with its own
saved configuration. Individual agents can also
be invoked through the direct execution endpoint with their schema-specific input.

After successful checks, the backend captures an immutable public configuration
snapshot in `agent_execution.configuration_snapshot`. `configuration` is returned
by execution HTTP endpoints and version history; it contains model, provider,
credential ID/name, temperature and tokens, never the key. Historical executions
return null. The project **Audits** section displays **Configuration used**.
Lifecycle WebSocket contracts stay unchanged; the frontend retains the HTTP
snapshot alongside lifecycle updates.

Empty generation parameters resolve to explicit backend defaults (temperature
`0.2`, maximum tokens `1000`) before capture and dispatch. The agent-server receives
the selected provider/model/key and resolved parameters in `config`. Changes in
Settings or key rotation affect future starts, not the captured request of a run
already in progress. Secrets remain transient in backend dispatch memory and are
not duplicated in execution storage.

Version selection, evaluation and execution creation for project analysis are
transactional and happen after verification. A failed or stale check leaves no
partial evaluation/version/execution. A second open analysis for the same version
is checked again inside the transaction.

Migration `20261012000000_agent_settings_defaults` makes model and credential
assignments nullable, preserving existing settings and foreign-key references.
Migration `20261012010000_agent_configuration_execution` adds verification metadata,
model/credential revisions and historical execution snapshots. Apply migrations
from `backend/` before restarting both services:

```bash
pnpm exec prisma migrate deploy
pnpm exec prisma generate
```

## Token budget persistence

Migrations `20261014000000_agent_token_budget` and
`20261014010000_agent_absolute_token_limit` introduce nullable `tokenBudget` and
`absoluteTokenLimit` settings. These describe the cumulative input/output
budget of an agent execution; `maxTokens` still describes output per model call.
The settings PUT endpoint accepts both new fields. Omission preserves a saved
value and null clears its override. Both values are positive 32-bit integers.

When both overrides are present, `absoluteTokenLimit` must be greater than or
equal to `tokenBudget`; invalid combinations are rejected with `422`. Equal
values mean a strict budget. The tolerance margin is derived as
`absoluteTokenLimit - tokenBudget`, rather than stored as a percentage.
Null means the runtime must resolve that parameter's default. No new default
budget or absolute limit is assigned by these migrations.

The second migration converts previously saved percentages to their calculated
absolute limits and removes the old percentage column. Previous execution
snapshots keep their captured absolute limit and drop the percentage property.

New execution snapshots retain these values. Changing either setting invalidates
the current configuration fingerprint and cannot change an existing snapshot.
Historical snapshots without the new properties remain readable.

This persistence phase stores configuration; passing it to the runtime budget
and enforcing tolerance will be integrated in the execution phase.

## Verification

From `backend/`:

```bash
pnpm exec tsx --test src/tests/agent-catalog.integration.test.ts src/tests/agent-settings.integration.test.ts src/tests/agent-configuration-execution.integration.test.ts src/tests/openapi.integration.test.ts
```

The catalog integration uses a real local HTTP discovery stub and migrated SQLite
database to verify startup synchronization, previously unknown server identities,
optional children, reparenting, retirement, idempotence, retained assignments and
history, invalid graphs, offline recovery and rejection of invented local agents.
Settings tests inject a fake catalog source and cover assignment persistence,
provider mismatch, decimal/null values and credential exclusion.

Frontend coverage lives in `AgentsSettings.test.tsx`, `AgentSettingsCard.test.tsx`
`AgentAccessVerification.test.tsx` and `SettingsPage.test.tsx`. Agent-server
`tests/test_model_access.py` checks access probes, sanitized failures, actual
provider routing and generation parameter application without external requests.

## Manual evidence

1. Register a model supported by its provider and an appropriate credential.
   Save its assignments in Settings, then click **Verify access**: capture the
   **Verified** state and check timestamp.
2. Use an invalid key: capture **Needs attention** and the verification error.
   Attempt **Analyze**: capture the error and **Review agent configuration** link;
   no execution is created. An unavailable provider/server also blocks the start.
3. Restore a valid key, start an analysis and open **Audits**. Capture
   **Configuration used**, including the run ID and generation parameters.
4. While that run is open, save different settings or rotate its key. The existing
   run retains its snapshot; a new execution uses the updated configuration.
   For deterministic automated evidence, the integration test holds the first
   execution open, changes settings/key, and compares both captured requests and
   persisted snapshots.
5. Reload the project to show the snapshot is persisted. Rename its model or edit
   its API key and return to Settings: the previous verification becomes
   **Not verified**. A name-only credential edit preserves key validity.
## Category assignments and effective access

The local backend connects to agent-server using `127.0.0.1` to match its IPv4
listener. On Windows, `localhost` can select an IPv6 Vite listener on the same
port and return frontend HTML instead of the agent catalog. Settings → Audit
offers catalog synchronization and explains missing category metadata instead of
rendering an empty card grid.

`PUT /api/agent-settings/categories/:attribute` accepts `{ modelId, credentialId }`
and returns the full public settings list. Membership comes exclusively from the
synchronized `quality_attributes`. In a single transaction, the backend resolves
available model participants to their unique model configuration owners and assigns
the pair to all of them. Unknown categories, invalid owners or provider mismatch
reject the entire write. Generation parameters and budgets remain individual.
Access verification receipts are invalidated after a category assignment.

Settings → Audit builds its category cards from this metadata, including newly
declared categories. Mixed assignments are indicated and can be unified even if
the selected pair matches the representative agent. Shared owners may affect more
than one category; deterministic agents have no model assignment.

Public configuration and verification for a shared agent reflect its declared
model owner. `POST /api/agent-settings/:agentType/verify` resolves that owner and
records the provider check there; deterministic/unavailable agents return 422.
The frontend displays shared access as read-only and omits model access controls
for deterministic agents. A dirty form does not display a saved verification badge
as proof of access to its unsaved selection.
