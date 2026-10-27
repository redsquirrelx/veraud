# Fastify and execution contracts

The backend owns execution-row IDs and treats agent results as opaque JSON. Keep the
following routes, field spellings, catalog identities and lifecycle semantics stable.
Implementation owners are listed in [`architecture.md`](architecture.md).

## Agent-server HTTP

| Operation | Contract |
| --- | --- |
| `GET /api/status` | `{ "status": "ok", "service": "agent-server" }`; does not probe providers or callbacks |
| `GET /api/agents` | Directly executable registered agents only |
| `GET /api/agents/catalog` and `/{agent_id}` | Catalog schema version `1.0`; IDs/aliases, roles, hierarchy, execution modes, attributes, availability and user-only config descriptors. Discovery creates no model or repository toolset |
| `GET /api/agents/{agent_type}/schema` | The direct agent's existing typed input/output schemas |
| `POST /api/agents/run` | Request contains `agent_type`, `config`, `input`, optional `execution_id`; response `{agent_type, result}` with object result |
| `POST /api/agents/verify-access` | Explicit selected model/credential check; no server-key fallback |
| `GET /api/pipelines` | Names remain `functional-adequacy`, `project-architecture`, `quality-audit` |
| `POST /api/pipelines/{name}/run` | Preserve `input`, `config`, `stage_configs`, `execution_ids`, `timeout_seconds` and stage-keyed result |
| `POST /api/audits` | Accepted asynchronous lifecycle remains HTTP 202; do not change validation-before-acceptance order |
| `GET /api/audits/{run_id}` | Current lifecycle and Blackboard snapshot; terminal states are completed, partial, failed or cancelled |
| `GET /api/audits/{run_id}/report[.docx]` | Canonical report and DOCX; generations remain separately retrievable |
| `POST /api/audits/reports/from-snapshot[.docx]` | Offline deterministic report from same-run evidence/findings/assessments; does not import into active Blackboard |

The pipeline stage IDs remain `orientation`, `architecture`, `semantic_validation` for the
project pipeline. The quality workflow keeps its existing `audit_root(attributes)` callback
selection and exact model-configuration groups. Internal participants do not become direct
HTTP agents. DAST remains `not_executed`; proposed patches and heuristic findings are not
advertised as technically verified.

The 422 handler strips `input` and `ctx` because config input can contain credentials. Preserve
safe domain errors and do not return exception/provider payloads containing secrets.

## Outgoing Fastify callbacks

| Event | Request |
| --- | --- |
| Running | `POST /api/agent-executions/{id}/running`, `{}` or `{ "runId": "..." }` |
| Progress | `POST .../{id}/progress`, camelCase `inputTokens`, `outputTokens`, `estimatedTokens`; cumulative; unknown counts remain null |
| Completion | `POST .../{id}/completion`; `Completed`/`Failed`; `result` is a **JSON-serialized string**, never a nested object; usage fields remain camelCase |
| Invocation | `POST .../{id}/invocations`; current snake_case receipt, lineage, phase sequence and timestamps; no prompts, evidence or credentials |

Backend-created execution IDs are only updated, never created, by the callback client. A
callback transport failure must not discard successful agent work. `X-Agent-Secret` remains
optional and is not authorization unless the backend separately implements it.

## `quality-audit` artifact and reconciliation

The pipeline artifact remains `{"audit": {"attributes", "status", "run_id", "report",
"blackboard", "docx_base64"}}`. Fastify may reconcile an existing run using GET snapshot,
report and DOCX; it must not replay the POST after an uncertain transport result. Do not move
large report artifacts into each invocation receipt.

## Agent, graph and config extension checklist

1. Put an attribute-specific graph, state, policies, prompts and request/result schemas in
   that implementation's existing package. Add a manager/coordinator/registry entry only when
   the topology genuinely has that role.
2. Put cross-agent execution in `runtimes/`; pass contracts and callbacks as dependencies.
   Reuse snapshot, fresh toolset, deadlines, pacing, quotas and accounting.
3. Add shared config fields only in their owning `config/agents/` class. Local `config.py`
   needs real unique specialization. New fields are developer-level unless explicitly approved.
4. Preserve typed schemas, identity, evidence provenance, uncertainty, partial results and
   route/termination reasons. A missing citation or failed tool call must not become success.
5. If an API field, stage ID, alias, callback body or catalog descriptor changes, treat that
   as a coordinated contract change; this refactor does not require Fastify changes.

Focused contract checks: `tests/test_openapi_contracts.py`, `tests/test_agent_catalog.py`,
`tests/test_pipeline_ports.py`, `tests/test_usage_callbacks.py` and `tests/test_audits.py`.
