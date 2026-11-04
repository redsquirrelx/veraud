# Tasks: Git commands and service procedures

The first installed service task is `graph.extract`; see [project-graph.md](project-graph.md)
for its asynchronous API, callback lifecycle, artifact storage and migration.

`TaskRunner` manages queueing, scheduling, state persistence and `task.updated`
events. Executors describe how work runs; the runner itself does not execute Git.

- `git.task-executor.ts`: existing Git commands, timeouts, CLI output, checkout
  access and project synchronization status.
- `service.task-executor.ts`: explicitly registered backend procedures. A handler
  can invoke an application service, make an HTTP request through an existing
  client or perform local work without launching a process.
- `task.types.ts`: shared command, execution-plan and scheduling contracts.

## Register and launch a procedure

Wire handlers at the backend composition root, closing over the services they
need. `buildApp({ ..., taskHandlers })` registers them alongside Git. For a runner
constructed directly:

```ts
const runner = new TaskRunner(taskRepository, projectRepository, gateway, [
  gitTaskExecutor(workspaceDir),
  serviceTaskExecutor({
    "project.index": {
      projectAccess: "shared",
      async run(input, { projectId, taskId }) {
        const revision = validateIndexInput(input) // Validate unknown input here.
        await indexService.index(projectId, revision, taskId)
      },
    },
  }),
])
const tasks = new TaskService(taskRepository, runner)
const { result } = await tasks.launch(
  projectId,
  "Index selected revision",
  serviceTask("project.index", { branch, commitHash }),
)
```

This illustrates wiring an application service, not an installed indexer or graph
integration. No procedures run automatically after cloning. No arbitrary URL,
shell-command or procedure-launch HTTP endpoint is added.

`launch` retains its existing contract: it creates a persisted task, enqueues it
and **awaits completion**. Services receive task/project IDs plus their input. A
resolved handler succeeds; a rejected handler fails. Optional output is returned
to the caller, and explicit log trails are capped at 4,000 characters. CLI exit
codes remain available for Git; procedures normally have no exit code.

## Scheduling

Handler policies are declared by trusted backend code, not supplied in input:

| Policy | Behavior |
| --- | --- |
| No `projectAccess` | Independent work; does not acquire a checkout lock. |
| `projectAccess: "shared"` | Concurrent checkout readers; waits behind a writer. |
| `projectAccess: "exclusive"` | No other checkout work for that project. |
| `serialGroup: "indexer"` | One task in that group at a time across projects, FIFO. |
| `initializesProject: true` | Requires exclusive access; reserves the checkout before waiting readers and fails queued checkout dependents if initialization fails. |

Git keeps its previous behavior: clones are globally serialized, pending clones
reserve their project's checkout, reads can overlap, and writers are exclusive per
project without reader overtaking. Only clone/pull/fetch update the project's
sync status and timestamp. Service tasks do not claim the project was synced.

## Compatibility and limits

- Existing HTTP/WebSocket shapes and statuses are unchanged, including the legacy
  spelling `Succeded`. A service task's persisted `kind` is its registered name;
  `command` is null. Existing Git kinds and diagnostics are retained.
- Inputs and return values are not stored in task rows. Handler output/logs must
  exclude secrets. Unexpected service exception messages are not persisted;
  unknown handlers become failed tasks rather than remaining queued.
- Queue, inputs and checkout locks are **in memory**, scoped to one runner.
  Persisting task status does not provide restart recovery, retries, distributed
  locking or exactly-once execution. Service handlers own transport deadlines;
  there is no new cancellation/timeout mechanism for arbitrary procedures.
- Audits remain managed by `AgentExecution`/`Evaluation`. No database migration is
  required for this refactor.

Focused tests:

```powershell
pnpm exec tsx --test src/infrastructure/task-runner/*.test.ts src/modules/task/*.test.ts src/modules/project/project.service.test.ts src/projects.integration.test.ts
pnpm exec tsc --noEmit
```
