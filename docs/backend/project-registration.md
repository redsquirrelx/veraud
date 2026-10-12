# Backend Contract — Project Registration

`POST /api/projects` registers a project from a GitHub HTTPS or SSH URL only if it
clones successfully. The request waits for the clone; the success toast
is the clone confirmation. No audit yet.

Source of truth: `backend/src/modules/project/`, `modules/task/`,
`infrastructure/github-client/`, `task-runner/`, `realtime-gateway/`

## `POST /api/projects`

Request: `repositoryUrl` (string, required) — `https://github.com/{owner}/{repo}`,
`git@github.com:{owner}/{repo}.git` or `ssh://git@github.com/{owner}/{repo}.git`
(`.git` and trailing `/` allowed). The backend detects the transport from the URL.
For SSH, Git uses the SSH configuration of the user running the backend; the
application does not manage keys or prompt for credentials.

`shallowClone` (boolean, optional, defaults to `false` when omitted):
`false` executes `git clone <url> <destination>`; `true` executes
`git clone --depth 1 <url> <destination>`, initially downloading only the latest
commit of the default branch. Both modes support HTTPS and SSH.

```json
{ "repositoryUrl": "https://github.com/fintech-core/payment-gateway-v2", "shallowClone": true }
```

Response `201`: `id` (number), `repositoryOwner` (string), `repositoryName` (string), `status` (`QUEUED`).

Flow: validate URL → for HTTPS fetch repo metadata (`GET /repos/{owner}/{repo}`),
but for SSH skip the public GitHub API (private repos may return `404`) → reject
duplicates by owner/name (and by GitHub ID for HTTPS) → persist project (`QUEUED`)
+ `task` (`Queued`, `description: "cloning {owner}/{repo}"`) → broadcast the queued
task → await clone into `appdata/workspace/{githubId}-{owner}-{repo}` for HTTPS
or `appdata/workspace/project-{projectId}-{owner}-{repo}` for SSH → on success
return `201`, on failure roll back (delete task + project) and return `422`.
Every task transition broadcasts `task.updated` on `/ws`.

## `GET /api/tasks/active`

Read-only. Returns tasks `Queued`/`Running`: `id`, `projectId`, `repositoryOwner`, `repositoryName`, `description` (`"cloning {owner}/{repo}"`), `status`, `kind` (git command, e.g. `clone`, `pull`, `list-branches`), `exitCode` (number or null).

## WS `/ws` — `task.updated`

Both `GET /api/tasks/active` and `task.updated` include `command` (string or null).
The runner saves a readable representation of the executable and arguments
before announcing `Queued`, then executes those same arguments via `execFile`.
Arguments needing quotes use JSON string notation; this is a display value,
not a shell script. Older tasks without a recorded command return null.

Per transition: `id`, `projectId`, `description`, `status` (`Queued`/`Running`/`Succeded`/`Failed`), `kind`, `exitCode` (number or null). The frontend uses `kind` to silence read-only tasks (`list-branches`, `rev-parse`, `log-commits`) unless they fail.

Agent executions broadcast `agent-execution.opened` / `agent-execution.updated`; see `agent-execution.md`.

## Errors

| Code | Meaning |
|---|---|
| `400` | Malformed URL or wrong host |
| `409` | `githubRepositoryId` already registered |
| `422` | GitHub unreachable, repo missing, or clone failed (`message` is user-facing, nothing stored) |

## Data

`project`: `githubRepositoryId` (GitHub numeric id), `repositoryOwner`/`repositoryName`,
`shallowClone` (boolean, preserved when recloning; defaults to `false`),
`status QUEUED`, `name` null until synced, no `project_version` yet.
`task`: `projectId`, `description`, `status`, `kind` (command that created it, `unknown` for rows predating the column), `exitCode`, `logTrail` (last 4000 chars, always saved on finish).

Out of scope: Agent invocations are covered in `agent-execution.md`.
