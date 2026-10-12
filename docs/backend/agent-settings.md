# Backend agents and saved configuration

`GET /api/agent-settings` lists the agent types explicitly declared in backend
workflows and merges them with backend `AgentSettings` rows. Swagger describes
the response under **Agent Settings** at `/docs`.

## Source of available agents

`agent-types.ts` defines the shared backend catalog, currently containing
`analyzer` and `dummy`. The project-analysis workflow uses the same `ANALYZER_AGENT_TYPE`
constant. The frontend renders the backend response without its own type list.

Each declared type appears even if it has no saved configuration. Settings for
other types are omitted. The endpoint
does not contact the agent-server and works while that service is offline or its
URL is not configured. Adding a supported backend agent requires updating the
backend catalog alongside its workflow.

## Automatic defaults

At application startup, `AgentSettingsRepository.ensureSeeded()` creates a row
for every type in `BACKEND_AGENT_TYPES` that does not yet exist. The operation
is transactional and idempotent. Existing selections, execution options and rows
outside the catalog are retained.

New rows contain only `agentType`; model, credential, temperature and maximum
tokens are null. They appear as **Not configured** until selections are assigned.
The backend does not choose a model or credential automatically. Executions
without an assigned model and credential are rejected with `422`.

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
Card per backend type, with configured/pending status and editable model and
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
The response is the updated agent configuration without API keys. Unknown backend
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
before a workflow creates any records. Project analysis currently requires only
`analyzer`; `dummy` can be invoked through the direct execution endpoint.

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
```

## Verification

From `backend/`:

```bash
pnpm exec tsx --test src/tests/agent-settings.integration.test.ts src/tests/agent-configuration-execution.integration.test.ts src/tests/openapi.integration.test.ts
```

The integration check uses a temporary database without an agent-server to
cover backend type selection, missing settings, exclusion of unrelated settings,
provider mismatch, decimal/null values and credential exclusion. It also verifies
startup defaults, repeated seeding without overwrites and recreation of missing
catalog rows. Write coverage checks successful assignment, persistence, preserved
execution options, unknown types, missing selections and rejected provider mismatches.

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
