# Maintainability agents

Agents are grouped by their place in the audit hierarchy:

```text
maintainability/
├── manager/
├── modularity/
│   ├── coordinator/
│   ├── responsibility/
│   ├── architecture_boundary/
│   └── dependency_impact/
└── reusability/
    ├── coordinator/
    ├── component_adaptability/
    ├── reuse_opportunity/
    └── abstraction/
```

## Reading the code

Start with the smallest module that answers your question:

| Question | Module |
| --- | --- |
| Public class, request, configuration and execution binding | `agent.py` |
| Graph nodes, routes and domain execution policy | `execution.py` |
| Candidate selection before investigation | `discovery.py`, where present |
| Consolidation, synthesis projections and proposal checks | `synthesis.py`, where present |
| Manager accounting, nested provenance and coverage checks | `manager/validation.py` |
| Agent-specific request/result contracts | Local `schemas.py` (canonical definitions) |
| Neutral investigator envelope and evidence contracts | [`../../contracts/audit.py`](../../contracts/audit.py) |
| Generic delegation/synthesis envelopes | [`../../runtimes/coordination/contracts.py`](../../runtimes/coordination/contracts.py) |
| Model instructions | Local `prompts/` |

The small architecture-boundary binding remains self-contained in `agent.py`.
Other public `agent.py` modules reexport their execution classes so existing imports
continue to resolve to the same objects. Read shared runtime code only when the
question concerns common model calls, tools, budgets, pacing or delegation.
Cross-round record accumulation is shared in
[`../../runtimes/investigation/records.py`](../../runtimes/investigation/records.py);
domain evidence acceptance stays in each investigator's execution module.

## Configuration and usage

Each agent keeps its implementation, contracts, README and `prompts/` together.
Agent-exclusive policy lives in a local `config.py` only where needed.
Common execution/provider/delegation controls live in [`agent-server/config/agents/`](../../../../config/agents/README.md).
Each agent's configuration inherits only its applicable common family; the shared
catalog publishes validated defaults, effective JSON Schema and panel field groups.
Shared orchestration lives in [`../../runtimes/coordination/`](../../runtimes/coordination/README.md);
modularity, reusability and manager bind their own graphs over that neutral runtime.
Import from the concrete agent package, for example:

```python
from server.agents.maintainability.manager import MaintainabilityManagerAgent
from server.agents.maintainability.modularity.coordinator import ModularityAgent
from server.agents.maintainability.modularity.architecture_boundary import ArchitectureBoundaryAgent
from server.agents.maintainability.reusability.coordinator import ReusabilityAgent
from server.agents.maintainability.reusability.abstraction import AbstractionAgent
```

Execution remains `await agent.run(fresh_toolset, typed_request)`. Standalone runners
and deterministic/optional live tests remain in `src/test-agents/`.
