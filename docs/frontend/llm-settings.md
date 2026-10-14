# Frontend Contract — Settings LLM Admin

The `Models & credentials` tab on `/settings` administers LLM
models and API keys against the backend (`docs/backend/ai-providers.md`).
It owns no persistence: `useAiProviders` loads and mutates, the page
maps provider-scoped data into two flat single-select `ItemList`s
with domain templates, and outcomes toast globally (see
`docs/frontend/toasts.md`).

The separate `Agents` tab loads backend-declared types through `GET /api/agent-settings` and
allows editing saved assignments in Cards and the Drawer, including generation
parameters. Both show access-verification state and a **Verify access** action.
Successful saves toast; failed saves retain drafts. Settings remembers its active
tab through the infrastructure storage abstraction (`settings.activeTab`). See
[agent settings](../backend/agent-settings.md). `Preferences` contains task
notification visibility settings.

## Agent execution budgets

The agent Drawer edits `tokenBudget` (**Initial token budget**) and
`absoluteTokenLimit` (**Absolute token limit**) as positive 32-bit integers.
When both are configured, the absolute limit must be at least the initial budget.
The Drawer displays the derived tolerance margin in tokens and percent; equal
limits mean no margin. Empty fields clear the corresponding overrides.
The agreed defaults are 160,000 tokens initially and 200,000 absolutely; the
Drawer shows both values and uses them to preview the margin for empty fields.
**Maximum output tokens per call** remains a separate generation parameter.

`AgentTokenUsage` renders cumulative input, output and estimated consumption in
the agent monitor and project stage status. It uses the execution's captured
configuration, supports percentages above 100%, and labels normal, tolerance and
absolute-limit states with text and color. The bar is relative to the absolute
limit, while the displayed percentage is relative to the initial budget. Its
expandable breakdown distinguishes reported counts from estimates and missing data.

The monitor retains up to 50 recent execution IDs under `agents.recentExecutionIds`
and refreshes them by HTTP on reload/reconnect. HTTP snapshots enrich lifecycle
events with configuration; merges preserve increasing usage and terminal status.
An HTTP hydration response arriving after a newer socket event does not overwrite
that event's lifecycle data. Project tracking also merges polling and live usage.

Audit history shows captured limits. A failed execution with a stored result is
labelled incomplete and links to the partial analysis; `token_budget_exhausted`
has a dedicated interruption message. Reaching a displayed limit does not itself
mark an execution as stopped: its lifecycle status still comes from the backend.

Source of truth: `frontend/src/pages/settings/SettingsPage.tsx`
(page), `ModelListItem.tsx` / `CredentialListItem.tsx` (row
templates), `frontend/src/features/llm-management/useAiProviders.ts`
(data), `frontend/src/infrastructure/http-client/httpClient.ts`
(AI calls).

## Data flow

`useAiProviders` fetches `GET /api/ai-providers` on mount
(`mounted` guard, `ApiError` message on failure) and exposes
`refresh` plus `add/removeModel` and `add/removeCredential`, each
mutating then refreshing. The page flattens providers into a models
array (`provider` name as description, real `inUse`) and a
credentials array (real `apiKeyPreview`, never the key), so both
lists stay provider-aware while rendering flat. Provider ids travel
as strings for `ItemSelector` and back to numbers for the API.
Selections are local string arrays, pruned on delete.

## Lists

Two `ItemList mode="single"` in one row (`Models`,
`Credentials`), fixed `240px` frame, skeleton rows while
`loading`, `No ... registered yet` when empty, backend message on
load failure. `ModelListItem` shows name plus provider with an
`In use` neutral badge and a remove square at the far right;
`CredentialListItem` shows name plus provider, a fixed `API key`
caption column, the preview column, the badge and the remove
square. Remove buttons are disabled while `inUse` (mirroring the
backend `409`); races still toast the backend message.

## Modals

Each `+` opens a narrow `Modal` (`Add a model`, `Add a
credential`) with a provider `ItemSelector` and labelled inputs
(model: name; credential: name plus password key), a centered
`Submit` disabled until complete, and an inline error line. Success
toasts globally (`Model o1 registered`), closes and refreshes;
failure toasts the backend message and keeps the modal open with
the inline error. Escape, overlay click and the X always close.

Out of scope: `agent_settings` assignment (which model and key each
agent uses), key editing (delete plus re-add), provider management
(backend read-only seed).
