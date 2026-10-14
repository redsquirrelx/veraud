# Generic Pipelines — Adding a New Pipeline

One service runs every pipeline by name. Adding a pipeline means registering
a `PipelineDefinition`; no service, router, or client changes are needed.

Source of truth: `agent-server/src/server/app/pipeline_service.py`
(`GenericPipelineService`, `PipelineDefinition`, `GenericReportingHooks`),
`agent-server/src/server/app/tracing_port.py` (`TracingBackend`),
`agent-server/src/server/app/callback_port.py` (`CallbackSink`).
Worked example: `project-architecture`
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

## Architectural review routing

`ProjectArchitecturePipeline` explicitly routes
`orientation -> architecture -> diagram_composition -> semantic_validation`.
The semantic node has a conditional edge back to `architecture` for actionable
missing-evidence requests or source-backed corrections to contradicted/overstated
claims. With `allow_return` enabled, at most one return is allowed; the revised
report passes through diagram composition and semantic validation again.
The graph state preserves both reports and both reviews, with independent tool
ledgers and the same snapshot, configured token budgets and remaining deadline.
Reviewer citations are guidance: the architect must inspect its own source.
Semantic persistence receives the full history only after the return is resolved,
so a first review does not prematurely close its backend execution row.

## Developed architectural reports

The architect explains concrete responsibilities, initiating/receiving operations,
connection mechanisms, representative flows, contrasts and scoped uncertainties.
`supporting_evidence` contains separate cited assertions for independent review;
8–16 findings are a guidance target for substantial projects, never a quota.
The report allows 12 organization units, 18 connections, 24 supporting findings,
10 deviations, 10 infrastructure findings and 4 observed paths. Claims may contain
up to 3,000 characters; the architecture JSON parser accepts up to 160,000 characters.

HTTP and investigation CLI defaults allow 40,000 output tokens per call,
80,000 tokens per objective and 160,000 total tokens, with up to 24 model calls
and 32 tool calls per stage budget. The architect uses its own 16-call/32-tool
limits; the semantic reviewer can use 24 calls/32 tools and selects up to 64 claims
instead of 18. More than 64 targets or exhausted budgets remain explicitly pending.
These are capacity limits, not a requirement to consume the budget or fill sections.

## Module relationship investigation

Every organization unit must have a `relationship_investigations` entry describing
its incoming/outgoing boundaries as connected, isolated or unresolved, with a scoped
assessment and actually inspected file IDs. Supported assessments must cite the unit's
own source; isolation needs positive inspection and does not prove global absence.

The host compares supported report connections with retained internal imports,
inheritance and other resolved relationships, including unassigned neighboring files.
These are navigation hints, never inferred runtime edges. Missing investigation entries
or unaddressed neighbors cause evidence recovery before architecture closure. Declaring
`unresolved` does not bypass recovery: while budgets remain, the host queues unread
accessible endpoints and caller/composition searches in batches of up to eight tools.
The next model turn must use these results to update connections and investigations.
Recovery actions are tracked so the host does not repeat the same failed read/search.
An unresolved boundary may close only with source citations from its own inspected unit,
`resolution_blocker` (`evidence_inconclusive` or `dynamic_resolution`) and a concrete
`blocker_reason`. Otherwise the host requires another assessment within the model-call
budget. Exhausted budgets, unavailable sources and incomplete assessments are recorded
as per-unit blockers in the partial result. Results
include `relationship_coverage`; the frontend lists each module's status and pending
endpoint paths and blocker reasons. Representative application coverage alone no longer establishes complete
relationship coverage.

Semantic review includes per-unit relationship-coverage targets, even if the architect
omitted an investigation. These host-generated targets are review questions, not accepted
claims. Known gaps cannot be approved as complete coverage; reviewers must request
concrete evidence or propose a scoped correction. Diagram composition still only consumes
the accepted report and cannot investigate or repair missing module connections.

## Architectural diagrams

Composition produces one primary view and up to two complementary `views`, each
referencing report organization units and connection claims. Views can explain
structure, dependencies, a representative flow, configured deployment or a custom
interpretation. Each has its own boundaries, layout, roles, mechanisms and scope;
components can recur across views but not within one view. Each view is rendered
as an independent Mermaid artifact. The backend persists the primary chart and its
additional views; the frontend shows separate titled panels with scope and limitations.
Structured view annotations preserve the full
report hash and view-specific semantic-review pointers.

`prompts/diagram.md` provides evidence-conditioned rules for hexagonal, clean/onion,
layered, MVC/MVP/MVVM, modular monolith, microservices/SOA, event-driven, CQRS/event
sourcing, pipes-and-filters/ETL, microkernel/plugins, client-server/BFF and peer-to-peer.
Mixed or unmatched patterns use freely selected custom layouts rather than forced
templates. Node roles and relation mechanism labels are independently reviewed.

Reported deviations use `/deviations/N` references and affected node IDs. The renderer
inherits the original observation, pattern expectation, evidence and certainty, adds
short amber D1/D2 callouts linked to affected components. Complete deviation text and
pattern expectations appear below each chart. A deviation is not automatically a defect
or a reviewer contradiction; its marker does not overwrite the component's review border.
The reviewer checks deviation placement separately. Invalid references reject the
composition; unplaceable observations must be explained in view limitations.

Composition allows 8,000 output tokens (bounded by the caller), 48,000 prompt/response
characters, and per-view limits of 12 nodes, 24 edges and 8 groups. It uses more detailed
report summaries, contrasts, supporting findings and deviations, but performs no new
source inspection. The architect must supply sufficiently granular responsibilities.

Composition now requires structure and dependencies views. A representative flow is
required when report connections explicitly declare `kind=calls` with supported source
claims. Connection kinds are included in semantic review context; generic relationships
and imports do not establish invocation. Without supported calls, flow omission is
recorded explicitly; without connections, the dependency panel explains the evidence gap.
The host validates required views and permits one directed correction (two composition
calls maximum). If the model omits views, returns invalid JSON/references or the provider
fails, deterministic report projections fill the required views. Valid model selections
are retained where possible. `composition_origin` distinguishes model, model_repaired
and host_fallback; fallback preserves the failure details and does not invent sources,
protocols or grouping. Caller cancellation still propagates.

Node fill encodes architect certainty (blue=supported, yellow=hypothesis, grey=unresolved).
Border and arrow colors encode independent semantic review (green=supported,
orange=overstated, red=contradicted, slate dashed=insufficient evidence, light grey=not
reviewed). Node borders are thin when unreviewed. Relationship arrows remain solid for
architect-supported claims and dashed for uncertain ones. Labels contain only names or
mechanisms; legends are outside the graph, preserving readability and layout space.

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
