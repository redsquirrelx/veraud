# Backend Contract — Project Architecture

`POST /api/projects/:id/architecture` runs the `project-architecture`
pipeline (orientation, then architecture, then semantic_validation) on a
checked-out version. `GET /api/projects/:id/versions` lists versions with all
three pipeline runs. The legacy `POST /api/projects/:id/analyze`
(analyzer + architect) is unchanged; see `project-analyze.md`.

Source of truth: `backend/src/modules/project/` (service, controller),
`backend/src/modules/agent-execution/agent-execution.service.ts`
(`openProjectArchitecturePipelineForProject`), agent-server
`POST /api/pipelines/{name}/run` with `name = "project-architecture"`.

## `POST /api/projects/:id/architecture`

Request: `branch` (same rules as `git/rev-parse`) and `commitHash` (7 to 40
hex chars), both required.

```json
{ "branch": "main", "commitHash": "a…a" }
```

Response `201` (`executions` keyed by stage name):

```json
{
  "versionId": 9,
  "evaluationId": 7,
  "executions": {
    "orientation": { "id": 11, "agentType": "orientation", "status": "Waiting", "...": "..." },
    "architecture": { "id": 12, "agentType": "architecture", "status": "Waiting", "...": "..." },
    "semantic_validation": { "id": 13, "agentType": "semantic_validation", "status": "Waiting", "...": "..." }
  }
}
```

Flow: validate branch/hash (`400` if malformed) → find project (`404` if
missing) → require a workspace checkout (`422` if none) → reject when the
same version already has an open run (`422`, names the blocking execution) →
verify all three saved stage configurations (`422` naming the offending
stage, e.g. `semantic_validation`) → transactionally upsert the version row
(reused when the commit was analyzed before), mark it selected, create a
fresh `Analysis` evaluation and three executions through
`openProjectArchitecturePipelineForProject`: one `Waiting` row per stage,
each with its immutable public `configuration` (no API keys), each
broadcasting `agent-execution.opened` → dispatch
`runPipelineByName("project-architecture", {root_path}, executionIds,
stageConfigs)` in the background (the `201` returns while stages are still
working). Each stage receives its captured transport configuration
explicitly, including its credential, on the agent-server.

Invalid configuration or access creates no partial
version/evaluation/execution records. When the pipeline cannot start at all
(unreachable agent-server, no pipeline support), all three rows fail closed
with the same error; anything after the hand-off is reported stage by stage
by the pipeline over HTTP callbacks. The internal `diagram_composition` node
has no row; its output ships embedded in the architecture result.

Each execution has the same shape as `GET /api/agent-executions/:id`.
`GET /api/projects/:id/versions` returns all three runs per version and
`derivedStatus` aggregates them (`Waiting` while any is open, `Failed` if
any failed, `Completed` only when all three complete). The UI tracks the
**semantic_validation** row: it finishes last.
