# Backend Contract — Project Listing

`GET /api/projects` returns every registered project with its selected
version (branch/commit, null until synced). Full list, no paging:
filtering and paging run client-side (local single-user).

Source of truth: `backend/src/modules/project/`

Current HTTP contracts: backend `/docs` ([documentation index](README.md)).

## `GET /api/projects`

Response `200` (empty array when none, never 404): `id` (number),
`repositoryOwner` (string), `repositoryName` (string), `cloneProtocol`
(`https` or `ssh`), `status`
(`QUEUED`/`READY`/`SYNCING`), `registeredAt` (ISO datetime),
`lastSyncedAt` (ISO datetime or null, set when a clone succeeds),
`branch` (string or null), `commitHash` (string or null).

Flow: controller → service passthrough → Prisma `findMany` ordered by
`id` with `selectedVersion` included → mapped rows.

See also: `agent-execution.md`.
