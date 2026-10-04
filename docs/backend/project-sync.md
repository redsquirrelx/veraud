# Backend Contract — Project Sync

`POST /api/projects/:id/sync` re-syncs a project with GitHub.
No files on disk → clones; attached checkout → `git pull`
(keeps the current branch and commit); detached HEAD → `git fetch`
(refreshes every ref without moving HEAD, since `pull` cannot merge
without a branch).

Source of truth: `backend/src/modules/project/`,
`infrastructure/task-runner/` (`pull`/`fetch` commands)

## `POST /api/projects/:id/sync`

No body. Response `200`: `id`, `repositoryOwner`, `repositoryName`,
`status` (`READY`), `registeredAt`, `lastSyncedAt` (just set),
`branch`/`commitHash` (nullable).

Flow: find project (`404` if missing) → task `pulling owner/repo`
(or `cloning owner/repo` when the workspace is empty, `fetching
owner/repo` when HEAD is detached, detected by reading `.git/HEAD`
without spawning git) → await the queued command → on success return
`200`, on failure roll back the task, restore the previous status and
return `422` (`message` is user-facing). Every transition broadcasts
`task.updated` on `/ws`.

## Errors

| Code | Meaning |
|---|---|
| `400` | Non-numeric id |
| `404` | Unknown project |
| `422` | Clone/pull/fetch failed, nothing persisted beyond the previous state |
