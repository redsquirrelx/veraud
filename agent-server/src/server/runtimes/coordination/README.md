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
