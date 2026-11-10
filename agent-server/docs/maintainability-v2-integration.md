# Maintainability V2 in the web audit

`quality-audit` and `/api/audits` execute the V2 Manager, ModularityCoordinator and
`architecture_boundary_doc_driven.ArchitectureBoundaryAgent`. Their public IDs remain
`maintainability_manager`, `modularity`, `architecture_boundary`. No V1 participant
is advertised in the production agent catalog or invoked by this hierarchy.

## Deployment and saved configuration

Restart agent-server after updating. Restart backend or call
`POST /api/agent-settings/sync`: backend pulls `GET /api/agents/catalog` and
synchronizes the available hierarchy. An unavailable catalog leaves the last
successful synchronization intact; it does not silently establish V2 availability.

Existing model assignments for retained IDs remain stored. The web audit keeps
its existing category-level model selection. Removed participants become undeclared;
their settings and historical executions are not deleted. Historical V1 reports
are not rewritten. Old selections are rejected rather than mapped to a substitute.
Saved developer overrides are revalidated against V2 contracts; unsupported fields
or limits need adjustment, not automatic widening or silent removal.

The only supported explicit `maintainability_selection` is
`{"modularity": ["architecture_boundary"]}`. Omitting it selects the available
hierarchy. This limits capability, not architectural compliance coverage.

## Input

The web configuration includes optional JSON input under `request`. The same object
is accepted by the backend audit endpoint and forwarded to agent-server. It is
validated against the V2 Manager's canonical request, not operating configuration:

```json
{
  "objective": "Investigar los límites arquitectónicos del alcance seleccionado.",
  "targets": ["src"],
  "constraints": ["No modificar el repositorio."]
}
```

`documented_architecture` optionally accepts a complete `ArchitectureContextResult`,
with its original provenance. This integration does not automatically run the
architecture-context agent or convert project architecture prose into verified
claims. Omitted documentary input stays absent. The UI validates JSON object shape;
agent-server validates the full contract. Reusing historical selection metadata
does not restore documentary input.

Only `documented_architecture`, `targets`, `constraints` and `continuation` may reach
the documentary investigator. Manager/coordinator objectives remain at their own
levels. Prompt overrides are not accepted by that investigator.

## Monitoring and results

The backend execution ID remains the callback target. Invocation receipts preserve
parent/child identities and V2 phases; the investigator uses its native deterministic
completion classifier, without a V1 finding-review verdict. Events flow through
the existing execution-tracking outbox and backend history. The outbox remains
volatile; this change adds no local persistence or delivery guarantee.

Investigator claims and evidence, coordinator assessment and complete native Manager
result are published to the shared Blackboard. The existing JSON/Word report and
snapshot export consume these records. Candidate findings without a review appear
as `unreviewed` (Sin revisión), not `insufficient_evidence`, accepted or verified.
Native limitations and conclusions remain in the original retained reports.
`completed` describes completed execution, never global compliance.

Collection, synthesis and finalization add no model calls. Cancellation, shared
budgets/accounting, repository access checks, pacing and provider quotas are reused.
