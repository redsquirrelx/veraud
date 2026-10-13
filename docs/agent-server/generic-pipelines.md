# Generic Pipelines — Adding a New Pipeline

One service runs every pipeline by name. Adding a pipeline means registering
a `PipelineDefinition`; no service, router, or client changes are needed.

Source of truth: `agent-server/src/server/app/pipeline_service.py`
(`GenericPipelineService`, `PipelineDefinition`, `GenericReportingHooks`),
`agent-server/src/server/app/tracing_port.py` (`TracingBackend`),
`agent-server/src/server/app/callback_port.py` (`CallbackSink`).
Worked examples: `architecture-audit` (inside `pipeline_service.py`),
`project-architecture`
(`agent-server/src/server/app/project_architecture_definition.py`).

## Concepts

- `PipelineDefinition`: `name`, `stages` (ordered row keys), plus callables:
  `parse_input(raw: dict)`, `build_agents(exec, config, stage_configs, parsed,
  timeout) -> (agents, ctx)`, `adapt_hooks(generic_hooks)`,
  `create_pipeline(agents, graph_hooks, ctx)`, `run_pipeline(pipeline, parsed,
  ctx) -> dict`. `ctx` is private per-run state threaded through the three
  calls. `agent_types` optionally maps a stage to a different model-config key
  (default: the stage name itself).
- `GenericPipelineService.run(pipeline, input, config, stage_configs,
  execution_ids, timeout)`: parses input, checks every stage has an execution
  id, builds agents, creates one `GenericReportingHooks` over the id map,
  adapts it to the graph's hook shape, creates the graph, and awaits
  `run_pipeline` under `tracing.wrap_pipeline` with the shared deadline.
  Unknown name → `UnknownPipelineError` (HTTP 404). `InvalidConfigError` and
  `FileNotFoundError` → 422. `TimeoutError` → `fail_open` + 504. Any other
  error → `close_failed` (first unfinished stage carries it, later stages are
  marked `Skipped`) + re-raise. Callbacks are always closed in `finally`.
- `GenericReportingHooks`: `on_stage_start(stage)` / `on_stage_result(stage,
  result)` close one backend row per stage. Graphs with their own hook names
  (e.g. `on_analyzer_start`) get a thin adapter in the definition — never in
  the service. Hook methods the graph probes with `getattr` (`on_stage_skip`,
  `on_architecture_revision`) may stay absent; internal nodes without a row
  (e.g. `diagram_composition`) must be filtered out by the adapter.
- Ports (injectable, default = current behavior): `TracingBackend`
  (`LangSmithTracingBackend`, `NoOpTracingBackend`) and `CallbackSink`
  (`BackendCallbackSink`, `NoOpCallbackSink`). A custom tracer or sink only
  implements the protocol.

## Steps

1. Build the agents and the LangGraph as usual under `server/agents/` and
   `server/pipelines/`. Agents stay stateless: no rows, no callbacks, no
   tracing calls inside. The graph must accept `hooks=None` (dev-runner mode).
2. Write `server/app/<name>_definition.py`:
   - Input schema (Pydantic): everything the graph needs that the backend can
     send (`root_path`, budgets, flags). Raise `InvalidConfigError` on
     validation failure. Bad repository roots raise `FileNotFoundError`.
   - `build_agents`: resolve each stage model with
     `exec.resolve_model_settings(stage, stage_config)` (merges
     `dev_agents_config` + request overrides + API key exactly once), then
     construct models/gateways/agents. Snapshot-bound pipelines collect the
     snapshot here with `RepositoryAnalysisService`. Set `ModelGateway(...,
     trace=True)` so model calls land under the pipeline span.
   - `adapt_hooks`: map the graph's hook calls onto
     `GenericReportingHooks.on_stage_start/on_stage_result`, filtering events
     without a backend row.
   - `create_pipeline` / `run_pipeline`: assemble the graph and return plain
     dicts (`result.model_dump(mode="json")`). Release owned resources
     (e.g. `close_model_clients`) in a `finally` inside `run_pipeline`.
3. Register it in `default_pipeline_registry()`. No API change: `GET
   /api/pipelines` lists it and `POST /api/pipelines/{name}/run` serves it
   (`{input, config, stage_configs, execution_ids, timeout_seconds}`).
4. Backend: add one agent type per stage in
   `backend/src/modules/agent-settings/agent-types.ts` (stage names double as
   agent types so transport keys match; see `project-architecture`), then use
   `runPipelineByName` + `createExecutionsForProject`. No client change.
5. Tests: definition parsing (defaults + 422), registry entry, hooks
   filtering with a recorder sink, failure/skip semantics, and one HTTP test
   per new endpoint behavior. Mirror
   `agent-server/tests/test_project_architecture_definition.py` and
   `backend/src/tests/project-architecture.integration.test.ts`.
