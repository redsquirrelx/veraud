# Agent server

Python service and CLI runners for repository analysis and evidence-grounded audits.

## Configuration layout

- `config/agents/`: shared agent configuration contracts, budgets, provider policy and panel catalog.
- `src/server/agents/<agent_path>/config.py`: settings exclusive to an individual agent.
- `src/server/config/`: service infrastructure such as logging, tracing and environment loading.
- `config/dev-agents.yaml`: local model/service presets; excluded from distributions.

See [`config/agents/README.md`](config/agents/README.md) for configuration levels and examples,
and [`../docs/agent-server/`](../docs/agent-server/) for service/pipeline documentation.

The distribution includes both the `server` and `config` Python packages, including
agent-local prompts. Local YAML presets are retained in the checkout only.

```powershell
uv run project-architecture --help
uv run pytest src/test-agents tests --ignore=tests/test_functional_adequacy.py -q
```
