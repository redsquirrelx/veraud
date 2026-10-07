# Frontend Contract — Settings LLM Admin

The `Models & credentials` card on `/settings` administers LLM
models and API keys against the backend (`docs/backend/ai-providers.md`).
It owns no persistence: `useAiProviders` loads and mutates, the page
maps provider-scoped data into two flat single-select `ItemList`s
with domain templates, and outcomes toast globally (see
`docs/frontend/toasts.md`).

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
