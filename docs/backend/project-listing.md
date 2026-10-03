# Backend Contract — Project Listing

`GET /api/projects` returns every registered project with its selected
version (branch/commit, null until synced). Full list, no paging:
filtering and paging run client-side (local single-user).

Source of truth: `backend/src/modules/project/`

## `GET /api/projects`

Response `200` (empty array when none, never 404): `id` (number),
`repositoryOwner` (string), `repositoryName` (string), `status`
(`QUEUED`/`READY`/`SYNCING`), `registeredAt` (ISO datetime),
`branch` (string or null), `commitHash` (string or null).

Flow: controller → service passthrough → Prisma `findMany` ordered by
`id` with `selectedVersion` included → mapped rows.

Out of scope: Audit/Agent modules.
