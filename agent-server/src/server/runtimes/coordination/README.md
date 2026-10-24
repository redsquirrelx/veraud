# Shared coordinator runtime

`CoordinatorExecution` owns bounded dispatch, semaphore/start pacing, child-envelope
reservation, fresh read-only toolsets, deadlines, provenance, collection, accounting
and evidence-based synthesis. `CoordinatorSynthesisExecution` reuses the budgeted
investigation model-call machinery. `CoordinatorAgent` provides their shared lifecycle.

This package imports **no concrete agent, registry, prompt directory or assessment type**.
It supplies no default audit dimension. Concrete coordinators bind their contracts,
registry, evidence/grouping policies, prompt paths and graph:

```text
runtimes/coordination/execution.py
├── CoordinatorAgent
│   ├── ModularityAgent
│   ├── ReusabilityAgent
│   └── MaintainabilityManagerAgent
└── CoordinatorExecution
    ├── ModularityExecution
    ├── ReusabilityExecution
    └── MaintainabilityManagerExecution
```

Modularity's routing/final report remain local. Reusability retains its exact five-node
conditional graph and its source-backed grouping/conflict guards. The manager retains
its exact seven-node coverage/refinement graph. All three share the same implementation
of subordinate dispatch rather than inheriting from a sibling agent.

`schemas.py` owns `Consumption`. `synthesis.py` owns dimension-independent stable IDs,
evidence/request keys, indexing and generic grouping helpers. Concrete synthesis
modules supply domain contracts and semantics. Shared configuration is owned by
`agent-server/config/agents/`; this package declares no execution settings.

## Finalized knowledge and targeted commitments

`knowledge.py` projects finalized hypotheses, validated analyses, coverage, diagnostics
and termination into synthesis. Concrete coordinators provide analysis/binding field
names and domain-specific extensions; raw `critical_review` is never an approval source.

Gaps carry `task_type` and optional `InvestigationCommitment` records (original invocation,
question, subject IDs, assessment IDs, boundary, context and validation issues). Related
assessment/candidate/hypothesis diagnostics become one subject-bound task while original
`missing_information` stays in the invocation. Failed planning remains an essential
failure; discovery omissions alone do not become mandatory investigations.

Assignments preserve commitments and pass them as request `follow_up`; investigators see
`follow_up_commitments` in their structured context and must retrieve/verify source anew.
Completed results that substitute another subject, original bound question, boundary or
context remain partial. External-context gaps are retained without repository redispatch.
An unchanged bound task receives at most one targeted attempt under existing budgets.

Source-inspection closure needs genuinely new source ranges/content across earlier rounds,
not a different retrieval UUID. A `validation_repair` can instead close with the same
source when a prior invalid bound assessment becomes source-backed and its associated
final hypothesis resolves. The model proposes closure; the host checks the transition.
Independently resolved bound tasks can close within an otherwise partial invocation;
unrelated unresolved work and historical records remain intact.

Consolidation retains original qualification text. Contexts, assumptions, conditions and
sharing boundaries participate in identity/merge guards; no confidence average is used.

Host-owned `CoordinatorContinuation` resumes an in-memory, same-snapshot assessment.
It retains immutable child receipts, original coverage plan, unresolved/resolved task IDs
and cumulative result consumption. Dispatch reservations and resource checks count only
new work; the collecting manager verifies the baseline and charges the consumption delta.
Continuation is not a model-supplied request field or a restart-resumable persistence API.
Existing Blackboard child publications are referenced instead of republished as new claims.
