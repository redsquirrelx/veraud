# Agent Development Rules

## Scope and terminology

These rules apply to `agent-server/`. All paths below are relative to that directory.
**MUST** indicates a requirement; **MUST NOT** indicates a prohibition.
`{agent_path}` is the directory of a concrete investigator, coordinator or manager under `src/server/agents/`.

## Placement and dependencies

| Element | Location |
| --- | --- |
| Configuration shared across agents or protocols | `config/agents/` |
| Configuration exclusive to an agent, coordinator or manager | `{agent_path}/config.py` |
| Agent-specific prompts | `{agent_path}/prompts/` |
| Neutral audit contracts | `src/server/contracts/audit.py` |
| Report agent and report contracts | `src/server/reporting/` |
| Project analysis agents and graphs | `src/server/project_analysis/` |
| Direct example agent | `src/server/examples/dummy/` |
| Shared coordinator and manager execution | `src/server/runtimes/coordination/` |
| Shared investigator execution | `src/server/runtimes/investigation/` |
| Repository snapshots, access and tools | `src/server/runtimes/repository/` |
| Common LLM contract (`Model`) and provider adapters | `src/server/infrastructure/llm/` |
| Provider construction, pacing and usage helpers | `src/server/infrastructure/llm/` |
| Service environment and logging | `src/server/config/` |
| Tracing port and provider quota ledger | `src/server/infrastructure/` |
| Direct/audit model configuration resolution | `src/server/app/model_configuration.py` |
| Shared per-audit model cache and repository-tool construction | `src/server/app/audit_resources.py` |

1. Shared execution infrastructure MUST live outside `agents/`. Dependency direction is `FastAPI/app composition → quality implementations → runtimes/contracts/infrastructure → shared configuration and deterministic services`.
2. A shared runtime MUST NOT import concrete agents, their registries, prompts or specialized contracts. It may import `contracts/audit.py` and `runtimes/coordination/contracts.py`.
3. Sibling agents MUST NOT inherit infrastructure from one another. They MUST use a common base and supply their specializations.
4. Each agent MUST retain its domain decisions, specialized contracts and graph topology.
5. Code extraction MUST preserve existing nodes, routes and termination rules unless a functional change is requested.
6. `src/server/agents/` MUST contain exactly `maintainability/`, `functional_adequacy/` and `security/` as source packages. Project analysis, reporting, examples and neutral contracts MUST remain outside it.
7. Canonical schemas for a maintainability investigator/coordinator/manager MUST live with that participant. Neutral envelopes MUST live in `contracts/` or `runtimes/coordination/contracts.py`; compatibility re-exports MUST point to the same classes and MUST NOT be used by production consumers.
8. `src/server/runtimes/`, `contracts/` and `infrastructure/` MUST NOT import `app/` or `api/`. FastAPI and composition modules may depend inward on those packages.
9. Discovery/configuration catalogs may import implementation modules lazily to describe contracts; they MUST NOT instantiate agents, models, repositories or toolsets.

## Configuration: one declaration per parameter

6. Each shared parameter MUST have exactly one owning class declaring its type, validation and base default.
   Example: `max_total_tokens` belongs to `TokenBudgetConfig` in `config/agents/budgets.py`.
7. Consumers MUST inherit or compose the owning contract. They MUST NOT copy its declaration or validator.
8. Differences in defaults or bounds MUST use the existing presets:
   `defaults` and `bounds`. An inherited field MUST NOT be redeclared with another `Field(...)`.
9. A preset is **data applied to the same field**, not another parameter or validation implementation.
   Shared presets belong to the common family; exclusive presets belong to the agent's `config.py`.
10. A local configuration file MUST contain genuine specialization: unique fields, presets, constraints or policy.
    A local `config/` package, an empty subclass or a `config.py` without specialization MUST NOT be created.
11. Coordinators and managers follow exactly the same placement rule as investigators.
12. Configuration MUST affect actual execution. Ineffective controls and duplicated panel defaults MUST NOT be added.
13. Parameters MUST NOT be conflated merely because their names match: inspect meaning, units and scope before unifying them.
    Global, per-child and per-objective budgets are distinct limits; their precedence MUST be preserved.
14. Objectives, criteria, targets, project context and results belong to request/output contracts, not operating configuration.

### Minimal example

```python
# {agent_path}/config.py: the shared field is already declared in config/agents/.
from typing import ClassVar
from pydantic import Field
from config.agents import InvestigationConfig

class ExampleConfig(InvestigationConfig):
    defaults: ClassVar = {"max_total_tokens": 150_000}
    max_candidates: int = Field(default=8, ge=1, le=40)  # Agent-specific field.
```

This does NOT redeclare `max_total_tokens`. Without unique fields, presets or policy,
the agent would use `InvestigationConfig` directly, without a local configuration file.

## Access levels

**Ownership** (`shared` / `exclusive`) and **access level** (`user` / `developer`) are independent axes.

| Level | Current controls |
| --- | --- |
| `user` | `max_total_tokens`, `timeout_seconds`, RPM/TPM quotas within `provider_rate_limits` |
| `developer` | Tools, prompts, context, per-response tokens, internal calls, retries, iterations, concurrency, delegation and algorithm tuning |

15. Every new field MUST be `developer` by default. User exposure requires an explicit decision in `user_fields`.
16. The user panel MUST use `describe_agent_config(...)` and `validate_agent_config(...)` from `config.agents.catalog`.
    It MUST NOT publish the full contract or accept internal fields even when those fields are valid runtime settings.
17. The full view MUST be requested explicitly with `level="developer"`.
    Internal configuration is validated with `validate_developer_agent_config(...)`.
18. User edits MUST be applied over a trusted server-side base, then the complete resolved contract MUST be revalidated.
    Omitted fields retain their values; `null` disables only the corresponding quota where the contract permits it.
19. Panel schemas and defaults MUST derive from the effective classes. A separate handwritten type/default catalog MUST NOT be maintained.
20. Credentials MUST NOT appear in panel descriptors. Selecting a level in Python does not replace HTTP authorization.

## Execution and verification

21. Refactoring MUST reuse existing budgets, pacing, tracing and error handling.
    It MUST preserve provenance, uncertainty, partial failures and resource accounting; missing evidence MUST NOT become success.
22. Repository audits MUST retain read-only access and existing per-run snapshot/toolset rules.
23. Moving modules MUST include updating imports, the catalog, prompt paths, documentation and packaging.
    Compatibility aliases, if retained, MUST refer to the same class; they MUST NOT duplicate it.
24. Relevant tests and Ruff MUST run against affected code.
    Configuration changes require checking effective schemas/defaults and actual consumption; runtime changes require checking graphs and routes.
    Test selection and source reads MUST target the affected behavior; full-suite runs require cross-cutting impact or unresolved failures.
    Tests MUST detect a specific relevant regression; redundant scenarios and assertions that merely mirror implementation MUST NOT be added.
25. Changes to the distribution layout MUST include building the package and verifying imports/resources outside the checkout.
    Skipped or blocked checks MUST be reported and MUST NOT be presented as verified.

Navigation map: [docs/architecture.md](docs/architecture.md).
HTTP and callback contracts: [docs/contracts.md](docs/contracts.md).
Configuration details: [config/agents/README.md](config/agents/README.md).
Runtime responsibilities: [runtimes/README.md](src/server/runtimes/README.md).
