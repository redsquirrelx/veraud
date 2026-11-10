# Project analysis pipeline

The project header's **Analyze** button runs `PROJECT_PIPELINE` in
`projectPipeline.ts`. This is separate from the legacy `project-architecture`
agent pipeline and from quality audits. The ordered steps are structural-graph
extraction, then the independent `architecture_context` agent. No audit is launched.

To add a step, append a `ProjectPipelineStep` to `PROJECT_PIPELINE`:

```ts
const nextStep: ProjectPipelineStep = {
  id: "next-step",
  // Optional translated name; otherwise the UI displays the step ID.
  // labelKey: "...", // an existing projects translation key
  async run(context, results, signal) {
    const graph = results.get("structural-graph")
    // Validate the preceding output, use the fixed project/branch/commit from
    // context, pass signal to requests, and await actual task completion.
    return graph
  },
}
```

Steps run sequentially and receive preceding results by ID. A rejected step stops
the run. The graph step waits for `Succeded` and `graphAvailable`, verifies the
commit and task identity, and reuses existing completed graphs or running tasks.
It never treats submission, a failed regeneration's previous artifact, or an
artifact for another commit as successful completion.

The context step calls `POST /api/agent-executions/direct` with
`{ agentType: "architecture_context", project: { projectId, branch, commitHash } }`.
The backend resolves the path and associates the execution with a project version.
The frontend waits for completion: the backend stores the canonical artifact and
terminal execution state atomically. Native `partial` coverage is shown explicitly;
failed or mismatched outputs stop the run. A new Analyze run starts a new context
attempt (or adopts an active one); previous artifacts remain in the backend.

Project maintainability audits require a saved usable context for their exact
project/commit. The audit UI checks metadata availability and has no manual JSON
input. At submission, the backend independently checks the prerequisite, injects
`request.documented_architecture` and pins the source identity in audit configuration.
Security/functional adequacy do not require this context. Analyze never starts an
audit automatically.

Architecture Context has its own model/credential card in **Settings → Audit**;
it does not inherit maintainability's category assignment. A configuration refusal
is reported as a context-step error with a settings link, not as graph failure.
No execution row exists for a launch rejected before configuration validation.
Retrying Analyze reuses the completed graph and retries context extraction.

The global monitor discovers active/recent execution IDs from
`GET /api/agent-executions/recent` on mount, reconnect and every ten seconds,
then hydrates compact monitor snapshots. Discovery prioritizes active work and
is bounded to fifty executions. Context snapshots retain the native outcome
without transporting documentary evidence. Its row is independent of quality
audits and does not offer unsupported audit cancellation/report actions.

The frontend blocks duplicate starts, version changes, sync and graph regeneration
while running. State is local to the mounted project page: leaving it aborts
frontend requests/waits, **not** already submitted backend tasks. Reopening the
page does not restore pipeline history or automatically resume future steps;
Analyze can reuse the existing graph. Submitted context runs save their results
without the page, but durable orchestration of not-yet-submitted steps would
require backend support.
