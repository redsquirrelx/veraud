# Backend Contract — Project Analysis

`POST /api/projects/:id/analyze` runs the architecture-audit pipeline
(analyzer then architect) on a checked-out version. `GET
/api/projects/:id/versions` lists versions with both pipeline runs.

Source of truth: `backend/src/modules/project/` (service, repository,
controller), `backend/src/modules/agent-execution/agent-execution.service.ts`
(`openPipeline`). Pipeline lifecycle: `agent-execution.md`.

## `POST /api/projects/:id/analyze`

Request: `branch` (same rules as `git/rev-parse`) and `commitHash` (7 to 40
hex chars), both required.

```json
{ "branch": "main", "commitHash": "a…a" }
```

Response `201`:

```json
{
  "versionId": 9,
  "evaluationId": 7,
  "executions": {
    "analyzer": { "id": 11, "agentType": "analyzer", "status": "Waiting", "...": "..." },
    "architect": { "id": 12, "agentType": "architect", "status": "Waiting", "...": "..." }
  }
}
```

Flow: validate branch/hash (`400` if malformed) → find project (`404` if
missing) → require a workspace checkout (`422` if none) → reject when the
same version already has an open run (`422`, names the blocking execution) →
upsert the version row (reused when the commit was analyzed before) → mark it
the selected version → create a fresh `Analysis` evaluation → `openPipeline`:
one `analyzer` row plus one `architect` row, both `Waiting`, each broadcasting
`agent-execution.opened` → dispatch the pipeline in the background (the `201`
returns while both agents are still working).

Each execution has the same shape as `GET /api/agent-executions/:id`.
The UI tracks the **architect** row: it finishes last, so its completion is
the pipeline's completion. The analyzer row is visible in the Dock alongside.

## `GET /api/projects/:id/versions`

Response `200` (empty array when none, never 404): one entry per version,
newest first:

```json
[
  {
    "id": 9,
    "branch": "main",
    "commitHash": "a…a",
    "analysisStatus": "Pending",
    "analyzedAt": null,
    "evaluationId": 7,
    "executions": [
      { "id": 11, "agentType": "analyzer", "status": "Completed", "...": "..." },
      { "id": 12, "agentType": "architect", "status": "Completed", "...": "..." }
    ],
    "derivedStatus": "Completed"
  }
]
```

`executions` holds the latest evaluation's runs, analyzer first (id order).
Versions analyzed before the pipeline change may carry a single row; showing a
stored run prefers the architect row and falls back to the analyzer.

`derivedStatus` collapses both rows: an open run (`Running` first, then
`Waiting`) wins; otherwise any `Failed` wins; `Completed` only when every row
completed; `Pending` when the evaluation has no rows yet, `NeverAnalyzed`
when there is no evaluation at all.

## Errors

| Code | Meaning |
|---|---|
| `400` | Non-numeric id, invalid branch or hash |
| `404` | Unknown project |
| `422` | Missing checkout, `analyzer`/`architect` not in `agent_settings`, the same version already has an open run, or the project is syncing (status `SYNCING`: a sync rewrites the checkout the pipeline reads) |

Sync and analysis exclude each other in both directions: `POST
/api/projects/:id/sync` answers `422` while any pipeline run
(`Waiting`/`Running`) is open on the project.

Out of scope: agent invocation details (`agent-execution.md`), version
picking UI.
