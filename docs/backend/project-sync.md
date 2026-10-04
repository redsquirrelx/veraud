# Backend Contract — Project Sync

`POST /api/projects/:id/sync` re-syncs a project with GitHub.
No files on disk → clones; existing checkout → `git pull`
(keeps the current branch and commit).

Source of truth: `backend/src/modules/project/`,
`infrastructure/task-runner/` (`pull` command)

## `POST /api/projects/:id/sync`

No body. Response `200`: `id`, `repositoryOwner`, `repositoryName`,
`status` (`READY`), `registeredAt`, `lastSyncedAt` (just set),
`branch`/`commitHash` (nullable).

Flow: find project (`404` if missing) → task `pulling owner/repo`
(or `cloning owner/repo` when the workspace is empty) → await the
queued command → on success return `200`, on failure roll back the
task, restore the previous status and return `422` (`message` is
user-facing). Every transition broadcasts `task.updated` on `/ws`.

## Errors

| Code | Meaning |
|---|---|
| `400` | Non-numeric id |
| `404` | Unknown project |
| `422` | Clone/pull failed, nothing persisted beyond the previous state |
