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
