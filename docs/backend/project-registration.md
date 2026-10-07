# Backend Contract — Project Registration

`POST /api/projects` registers a project from a GitHub URL only if it
clones successfully. The request waits for the clone; the success toast
is the clone confirmation. No audit yet.

Source of truth: `backend/src/modules/project/`, `modules/task/`,
`infrastructure/github-client/`, `task-runner/`, `realtime-gateway/`

## `POST /api/projects`

Request: `repositoryUrl` (string, required) — `https://github.com/{owner}/{repo}` (`.git` and trailing `/` allowed).

```json
{ "repositoryUrl": "https://github.com/fintech-core/payment-gateway-v2" }
```

Response `201`: `id` (number), `repositoryOwner` (string), `repositoryName` (string), `status` (`QUEUED`).

Flow: validate URL → fetch repo metadata (`GET /repos/{owner}/{repo}`) → reject duplicates by `githubRepositoryId` → persist project (`QUEUED`) + `task` (`Queued`, `description: "cloning {owner}/{repo}"`) → broadcast the queued task → await the queued clone into `appdata/workspace/{id}-{owner}-{repo}` (project root) → on success return `201`, on failure roll back (delete task + project) and return `422`. Every task transition broadcasts `task.updated` on `/ws`.

## `GET /api/tasks/active`

Read-only. Returns tasks `Queued`/`Running`: `id`, `projectId`, `repositoryOwner`, `repositoryName`, `description` (`"cloning {owner}/{repo}"`), `status`, `exitCode` (number or null).

## WS `/ws` — `task.updated`

Per transition: `id`, `projectId`, `description`, `status` (`Queued`/`Running`/`Succeded`/`Failed`), `exitCode` (number or null).

Agent executions broadcast `agent-execution.opened` / `agent-execution.updated`; see `agent-execution.md`.

## Errors

| Code | Meaning |
|---|---|
| `400` | Malformed URL or wrong host |
| `409` | `githubRepositoryId` already registered |
| `422` | GitHub unreachable, repo missing, or clone failed (`message` is user-facing, nothing stored) |

## Data

`project`: `githubRepositoryId` (GitHub numeric id), `repositoryOwner`/`repositoryName`, `status QUEUED`, `name` null until synced, no `project_version` yet.
`task`: `projectId`, `description`, `status`, `exitCode`, `logTrail` (last 4000 chars, always saved on finish).

Out of scope: Agent invocations are covered in `agent-execution.md`.
