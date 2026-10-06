# Backend Contract — Project Git Branches

`POST /api/projects/:id/git/*` runs local git commands as tasks so the
auditor can pick a version. State stays in the workspace `.git`; the DB
only gains `task` rows (always kept). Read tasks never touch
`project.status`; the forced checkout neither (it only moves HEAD).

Source of truth: `backend/src/modules/project/`,
`infrastructure/task-runner/` (`list-branches`, `list-tree`,
`rev-parse`, `checkout-detach`, `checkout-branch`, `log-commits`
commands)

## `POST /api/projects/:id/git/branches`

Body: empty object. Response `200`: `branches` (string array parsed
from `git branch -a`: star marker stripped, `remotes/origin/HEAD ->`
symlinks and `(HEAD detached` markers skipped, `remotes/<remote>/`
prefix shortened, deduplicated, locals first), `currentBranch`
(attached name or null), `detachedHash` (lowercase hash when HEAD is
detached, else null) plus `taskId` (number of the kept task). A plain
`git clone` fetches every branch but checks out only the default
locally; the remote ones surface here through their `origin/` refs.

## `POST /api/projects/:id/git/tree`

Body: empty object. Response `200`: `files` (string array of the paths
tracked at `HEAD`, from `git ls-tree -r --name-only HEAD`, relative to
the repo root and slash separated) plus `taskId`. `HEAD` is what makes
it follow the checked-out version: a detached commit returns that
commit's tree, an attached branch returns the branch tip. Read-only, so
the task never touches `project.status`.

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

## `POST /api/projects/:id/git/checkout-branch`

Body: `branch` (string, required, same rules as rev-parse). Runs
`git checkout --force <branch>` with argv (no shell), attaching HEAD
to the branch and clearing any detached state; remote-only branches
materialize as local tracking branches. Response `200`: `branch`
(cleaned) plus `taskId`. Nothing else is persisted.

## Errors

`400` for non-numeric id (Fastify pattern) or invalid branch, hash,
limit, offset (no task created). `404` for unknown project. `422` for
missing workspace checkout or git failure (task kept as `Failed`).
Every transition broadcasts `task.updated` on `/ws` with `id`,
`projectId`, `description`, `status` (`Queued`/`Running`/`Succeded`/
`Failed`), `exitCode`.

## Task output vs log trail

`task.log_trail` keeps only the last 4000 characters (debug aid), so
the runner also returns the full stdout in `TaskResult.output` and the
service parses that. Anything that reads a git listing
(`list-branches`, `list-tree`, `log-commits`, `rev-parse`) must use
`taskOutput(result)`, never `logTrail`: on a repo with a few hundred
files the trail alone truncates the list and silently drops the first
entries.

Out of scope: `ProjectVersion`, frontend selectors.
