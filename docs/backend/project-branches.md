# Backend Contract — Project Git Branches

`POST /api/projects/:id/git/*` runs local git commands as tasks so the
auditor can pick a version. State stays in the workspace `.git`; the DB
only gains `task` rows (always kept). Read tasks never touch
`project.status`; the forced checkout neither (it only moves HEAD).

Source of truth: `backend/src/modules/project/`,
`infrastructure/task-runner/` (`list-branches`, `rev-parse`,
`checkout-detach`, `log-commits` commands)

## `POST /api/projects/:id/git/branches`

Body: empty object. Response `200`: `branches` (string array of local
names parsed from `git branch`, star marker stripped) plus `taskId`
(number of the kept task).

## `POST /api/projects/:id/git/rev-parse`

Body: `branch` (string, required, trimmed, letters numbers dot
underscore slash dash, no `..`/`--`/leading dash slash dot, none of
`@{ ~ ^ : ? * [ \` and max 255 chars). Response `200`: `branch`
(cleaned), `commitHash` (40 lowercase hex from `git rev-parse`) plus
`taskId`.

## `POST /api/projects/:id/git/log`

Body: `branch` (same rules as above, required), `limit` (integer
optional, default 30, 1 to 100), `offset` (integer optional, default 0,
zero or greater). Runs `git log --format` with tab-separated hash and
subject plus `--max-count` and `--skip`. Response `200`: `branch`,
`commits` (array of `commitHash` lowercase plus `subject`), echoed
`limit`/`offset`, plus `taskId`.

```json
{ "branch": "main", "limit": 30, "offset": 0 }
```

## `POST /api/projects/:id/git/checkout`

Body: `commitHash` (string, required, 7 to 40 hex chars, case
insensitive). Runs `git checkout --force --detach` with argv (no
shell); on git failure the task is `Failed` and the API returns `422`
with the stderr in `logTrail`. Response `200`: `commitHash`
(lowercase) plus `taskId`. Nothing else is persisted.

## Errors

`400` for non-numeric id (Fastify pattern) or invalid branch, hash,
limit, offset (no task created). `404` for unknown project. `422` for
missing workspace checkout or git failure (task kept as `Failed`).
Every transition broadcasts `task.updated` on `/ws` with `id`,
`projectId`, `description`, `status` (`Queued`/`Running`/`Succeded`/
`Failed`), `exitCode`.

Out of scope: `ProjectVersion`, frontend selectors, remotes (`-a`).
