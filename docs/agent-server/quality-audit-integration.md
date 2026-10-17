# Project quality audits

The backend starts the `quality-audit` pipeline independently of
`project-architecture`. Configure and verify `maintainability_manager` in Agent
Settings, then select a checked-out project revision.

## Shared maintainability model selection

**Settings → Audit → Maintainability audit models** reuses the Agent Settings
card to select and save one model and credential for the entire hierarchy. The
saved `maintainability_manager` assignment is the common source for this UI.
No API keys are read by the browser.

On dispatch, the backend expands that saved selection into explicit
`stage_configs` entries in `POST /api/pipelines/quality-audit/run` for:

- `maintainability_manager`
- `modularity`, `reusability`
- `architecture_boundary`, `responsibility`, `dependency_impact`
- `abstraction`, `reuse_opportunity`, `component_adaptability`

Each entry carries `model` (`provider`, `name`, `temperature`, `max_tokens`) and
`api_key`. The direct `POST /api/audits` endpoint accepts the same complete map
under `agent_configs`. Incomplete or unknown agent maps are rejected before
execution. The hierarchy uses each named model for its actual coordinator or
investigator; the contract can therefore receive different model selections in
the future. Identical selections reuse one provider client and all created
clients are closed through the bounded cleanup lifecycle.

```http
POST /api/projects/{projectId}/audits
Content-Type: application/json

{
  "branch": "main",
  "commitHash": "<full 40-character commit hash>",
  "attributes": ["maintainability"]
}
```

The endpoint returns HTTP 202 with `versionId`, `evaluationId` and `executionId`.
`attributes` is a nonempty, unique list of implemented quality attributes; only
`maintainability` is currently supported. Unsupported attributes are rejected
before creating execution rows. The pipeline verifies the checkout's HEAD before
spending model calls and uses the existing maintainability hierarchy, budgets,
quota pacing and bounded deadlines.

The pipeline generates the existing `SoftwareAuditReport` and DOCX from the
run's Blackboard, including partial/failed audit outcomes. It does not reinterpret
the results with another LLM. The backend stores the original report JSON,
Blackboard snapshot and Word bytes in the audit execution result under an
evaluation of type `QualityAudit`. Architecture versions continue to select only
`Analysis` evaluations. No database schema migration is needed.

- `GET /api/projects/{projectId}/audits`: persisted audit history, with
  `executionStatus`, `auditStatus`, `runId` and `reportAvailable`.
- `GET /api/projects/{projectId}/audits/{executionId}/report`: canonical JSON.
- `GET /api/projects/{projectId}/audits/{executionId}/report.docx`: original DOCX.

## Run id during execution

The pipeline runs the audit through the application-wide `AuditService`, so the
run is visible in `GET /api/audits/{run_id}` and on `/blackboard?run_id=…` while it
is still running. Immediately after creating the audit, and before any model
call, the stage reports its id to the backend:

```http
POST /api/agent-executions/{executionId}/running
Content-Type: application/json

{ "runId": "<32 hexadecimal characters>" }
```

The body is optional: other agents keep calling this callback without one. The
backend accepts the id only on an open `maintainability_manager` row with no
stored result, and a malformed value is rejected with 400. `runId` therefore
appears in the audit history while the audit runs; the delivered report envelope
replaces it with the same identifier once the run finishes. The frontend shows
it next to a **Ver Blackboard** link as soon as it is known.

An execution marked `Completed` means its artifacts were delivered, not that its
quality coverage is complete. `auditStatus` and the report preserve `partial` or
`failed` evaluations. Transport/start failures instead close the execution as
`Failed`. Downloads require neither a live agent-server nor provider access once
the backend has persisted the artifacts.

In the project detail page, **Analyze → Mantenibilidad** opens **Audits**. Select
Mantenibilidad, start the audit, and use **Ver informe** or **Descargar informe
Word** when it finishes. The viewer shows the ten original report sections and
retains source references. Active runs refresh automatically and expose their
`runId` for live Blackboard inspection.
