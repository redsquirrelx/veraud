# Project analysis agents

```text
project_analysis/
├── project_orientation/
├── project_architecture/
└── project_semantic_validation/
```

Each agent keeps its implementation, local `config.py` and `prompts/` together.
Shared repository execution lives in `runtimes/repository/`, and shared
configuration remains in `agent-server/config/agents/`.

```python
from server.project_analysis.project_orientation import ProjectOrientationAgent
from server.project_analysis.project_architecture import ProjectArchitectureAgent
from server.project_analysis.project_semantic_validation import ProjectSemanticValidationAgent
```

Pipeline adapters and CLI entry points use these concrete packages. Configuration
catalog IDs remain `project_orientation`, `project_architecture` and
`project_semantic_validation`.
