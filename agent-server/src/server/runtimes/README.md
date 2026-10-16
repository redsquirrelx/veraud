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

The data-only module `server.agents.schemes.base` is the shared contract boundary
and may be imported by runtimes. It has no agent or runtime dependencies.
`server.agents.schemes.investigator`, `coordinator` and `manager` own category
contracts and maintainability specializations; runtimes must not import those.
Previous `schemas.py` paths re-export canonical classes for compatibility.

Shared configuration belongs to `config.agents`; exclusive configuration remains
in each agent's `config.py`. See [coordination/README.md](coordination/README.md)
for the shared orchestration contract.
