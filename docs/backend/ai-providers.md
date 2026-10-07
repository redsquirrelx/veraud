# Backend Contract ΓÇö AI Providers

`GET /api/ai-providers` lists the fixed providers with their models
and credentials; the `POST`/`DELETE` routes below manage models and
credentials scoped by provider. Providers themselves are read-only:
`OpenAI`, `Anthropic` and `Google` are seeded idempotently at boot
(`ensureSeeded`, skipped when the name already exists), so a fresh
database always serves the three. No task rows are involved: this is
plain CRUD, unlike the git commands.

Source of truth: `backend/src/modules/ai-provider/`
(`ai-provider.repository.ts`, `ai-provider.service.ts`,
`ai-provider.controller.ts`), seed list `SEEDED_AI_PROVIDERS`,
wiring plus CORS methods in `backend/src/app.ts`.

## `GET /api/ai-providers`

No body. Response `200`: array of `{ id, name, models,
credentials }` ordered by provider name. Each model is `{ id, name,
inUse }`; each credential is `{ id, name, apiKeyPreview, inUse }`.
`apiKeyPreview` is `****` plus the last four key characters (or just
`****` for keys of four or fewer chars): the full key never leaves
the backend. `inUse` counts `agent_settings` rows pointing at the
entry and is what disables the frontend remove buttons.

## `GET /api/ai-providers/:id`

No body. Response `200`: the same detail shape for one provider.
`404` for an unknown id (Fastify pattern rejects non-numeric ids
before the service runs).

## `POST /api/ai-providers/:id/models`

Body: `name` (string, required, trimmed, 1 to 128 chars, letters
numbers dot underscore dash slash colon, no `..`). Names are unique
per provider. Response `201`: `{ id, name, inUse: false }` (a fresh
model cannot be referenced yet).

## `DELETE /api/ai-providers/:id/models/:nestedId`

No body. Response `204` with no content. The model must belong to
the provider in the path, otherwise `404`. A model referenced by
`agent_settings` returns `409` and is kept.

## `POST /api/ai-providers/:id/credentials`

Body: `name` (string, required, trimmed, 1 to 100 chars, letters
numbers space underscore dash) and `apiKey` (string, required,
trimmed, 1 to 2000 chars, no whitespace). Names are unique per
provider. Keys are stored as received (plain text, single-user
localhost decision) and the response `201` carries only `{ id, name,
apiKeyPreview, inUse: false }`.

```json
{ "name": "prod", "apiKey": "secret-1234" }
```

## `DELETE /api/ai-providers/:id/credentials/:nestedId`

No body. Response `204` with no content. Same ownership and
in-use rules as models: foreign ids are `404`, referenced
credentials are `409`.

## Errors

`400` for invalid names or keys (nothing persisted). `404` for an
unknown provider, or an entry that does not belong to the provider
in the path (ids never leak across providers). `409` for duplicate
names per provider and for deletes blocked by `agent_settings`
references. Browser deletes need CORS: `app.ts` allows `GET, HEAD,
POST, PUT, PATCH, DELETE, OPTIONS` because the Fastify default
(`GET, HEAD, POST`) rejects the `DELETE` preflight.

Out of scope: `agent_settings` administration, key encryption at
rest, per-model capabilities and quotas.
