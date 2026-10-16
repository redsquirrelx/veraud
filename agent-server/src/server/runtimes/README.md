# Shared execution runtimes

This package owns reusable execution infrastructure outside concrete agents.

| Package | Responsibility |
| --- | --- |
| `investigation/` | Shared investigator graph, model calls, structured output, provider pacing and provenance validation |
| `coordination/` | Shared coordinator/manager lifecycle, bounded dispatch, collection, accounting and synthesis helpers |
| `repository/` | Read-only snapshots, access policy, tools, telemetry and execution budget enforcement |

Dependencies flow from `server.agents` to `server.runtimes`, then to shared
configuration and services. Runtimes must not import concrete agents, their
registries, prompts or specialized contracts. Agents provide those through hooks
and retain their domain-specific graph topology and policies.

Shared configuration belongs to `config.agents`; exclusive configuration remains
in each agent's `config.py`. See [coordination/README.md](coordination/README.md)
for the shared orchestration contract.
