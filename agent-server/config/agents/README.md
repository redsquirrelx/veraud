# Agent configuration: ownership and access levels

Configuration has two independent axes:

- **Ownership:** shared controls live in `agent-server/config/agents/`; agent-specific controls
  live in a single `[agent_path]/config.py` file.
- **Level:** `user` controls the audit's operating allowance; `developer` controls
  how the implementation performs the audit. A common field is not necessarily a user field.

## Levels

`POST /api/audits` admite `agent_defaults.max_model_calls`, junto a
`max_context_characters` y `max_total_tokens`, como configuración de desarrollador.
Por ejemplo: `"agent_defaults": {"max_model_calls": 30}` aplica el límite de
llamadas al modelo a los investigadores. `agent_defaults.max_tool_calls` establece
de igual forma las llamadas a herramientas de cada investigador. Los padres
mantienen sus presupuestos agregados.
Para editarlos explícitamente: `"call_limits": {"manager": {"max_model_calls": 400},
"coordinator": {"max_model_calls": 160}, "investigator": {"max_model_calls": 40}}`.
Cada nivel también acepta `max_tool_calls`, por ejemplo `"call_limits": {
"manager": {"max_tool_calls": 400}, "coordinator": {"max_tool_calls": 180},
"investigator": {"max_tool_calls": 50}}`. Los límites de herramientas incluyen
intentos fallidos; cada padre debe poder reservar la primera ronda completa de
hijos. La síntesis no requiere herramientas adicionales.
Estos valores tienen precedencia sobre el valor común. Se valida antes de iniciar
que cada padre pueda reservar la primera ronda de hijos y su síntesis. El consumo
de descendientes sigue contando contra los límites del padre y del repositorio;
las rondas posteriores dependen del presupuesto restante. Los campos omitidos
mantienen sus valores efectivos originales. Contexto y tokens personales siguen
aplicándose a todos los niveles mediante `agent_defaults`.

| Level | Controls | Purpose |
| --- | --- | --- |
| `user` | `max_total_tokens`, `timeout_seconds` | Cost and duration of the requested execution |
| `user` | `provider_rate_limits.requests_per_minute`, `provider_rate_limits.tokens_per_minute` | Global provider/model quota admission; null disables this caller's bound |
| `developer` | `tools`, `prompts`, permitted prompt nodes | Tool capabilities and cognitive instructions |
| `developer` | `max_model_calls`, `max_tool_calls`, `max_iterations`, `max_context_characters`, `max_output_tokens` | Internal graph, context and per-call bounds |
| `developer` | Schema/provider retries, retry backoff, request/start intervals | Transport and scheduling policy |
| `developer` | Rounds, invocations, parallelism, child envelopes, attempts per dimension | Hierarchical orchestration |
| `developer` | Dependency depth, candidates, groups, components, scans, excerpt sizes, claims and batching | Agent-specific investigation algorithms |

Structured responses use `max_schema_retries` for ordinary corrections (default: 1).
Investigator `evaluate_evidence` additionally uses `max_schema_recovery_attempts`
(default: 2), allowing four total attempts with the default settings. Contract-defined
validation feedback explains recoverable semantic errors without exposing provider
payloads. Repairs retain the current plan and evidence and consume the existing
model-call, token, context and active-time budgets. A valid evaluation can return to
inspection through the agent's existing routes; exhausted evaluation repairs terminate
with `schema_recovery_exhausted` and retain partial results.

Critical review checks that every candidate is classified exactly once, with no
unknown IDs. These semantic checks use the same bounded correction loop as schema
validation (`1 + max_schema_retries` attempts); exhausted review corrections also
report `schema_recovery_exhausted`. Investigation reserves an evaluation call and
the initial review plus its configured corrections. Small explicit call envelopes
reduce the review reserve to leave room for planning, inspection and evaluation;
all attempts still obey the hard effective call cap.

The default coordinator child envelope inherits the common investigator model-call
limit (currently 16), rather than imposing a separate 12-call preset. Explicit child
limits and the repository budget still cap execution through their minimum.

New fields are **developer-owned by default**. An agent can explicitly extend its
`user_fields` class policy when a new genuinely user-facing control is implemented.
That policy is validated against the real model fields. Its user settings model is
derived from the agent's effective fields, so local default/bound overrides remain
authoritative without copying schemas or maintaining parallel UI defaults.

## Structure

```text
agent-server/config/agents/
    base.py         immutable extra-forbid contracts
    budgets.py      single declarations of shared token/call/time/source limits
    user.py         AgentUserConfig, ProviderRateLimits
    developer.py    AgentDeveloperConfig, tool/prompt policy
    execution.py    composed runtime config and investigator/coordinator families
    repository.py   developer stage limits for the project-repository protocol
    repository_execution.py  shared repository execution envelope
    tools.py        developer read-only tool response limits
    provider.py     shared provider retry/spacing policy
    levels.py       level-specific models and validated user-edit application
    model.py        resolved model/settings/credentials for existing model clients
    catalog.py      per-agent descriptions and validation entry points
agent-server/src/server/agents/maintainability/<dimension>/<agent>/config.py
agent-server/src/server/agents/maintainability/manager/config.py
agent-server/src/server/project_analysis/<agent>/config.py
```

`AgentExecutionConfig` composes `AgentUserConfig` and `AgentDeveloperConfig`.
Common parameters are declared exactly once: for example, `max_total_tokens` is
owned by `TokenBudgetConfig`, used by both agent settings and repository
`ExecutionBudget`. Call budgets, timeout and excerpt size also have single owners.
Local classes declare only their unique fields; they never redeclare inherited ones.

Different roles retain their existing defaults and bounds through **data presets**:
`defaults` and `bounds` class metadata, applied centrally by `ConfigContract`.
For example, a manager selects a 1,000,000-token default without another
`max_total_tokens: int = Field(...)` definition. This is a preset of the same shared
field, not a second setting or validation implementation. Presets are absent from
runtime JSON. The effective JSON Schema and user views use the resolved fields.
The manager's child-envelope type is selected through the generic
`CoordinatorConfig[CoordinatorConfig]`, reusing the single `invocation_limits` field.

Existing agents still receive a **flat resolved runtime config** with nested quota
and child-envelope fields. Result schemas retain compatibility exports referring to
the exact same classes. Each local agent config inherits the applicable family and
declares its specialized policy/defaults. Modularity and reusability coordinators
share a coordinator family instead of inheriting each other's configuration.

Architecture-boundary, responsibility and both dimension coordinators have no unique
configuration fields or policy. They use the shared classes directly, without empty
local subclasses or `config.py` files; established public names remain aliases.
Reuse-opportunity and adaptability share excerpt controls; their discovery bounds
remain local developer settings. Local `prompts/` files remain beside their agents.

## User panel (default)

```python
from config.agents.catalog import describe_agent_config, validate_agent_config

panel = describe_agent_config("dependency_impact")  # level="user" by default
# Only user schema, defaults and groups; no prompts, tools or child schemas.

config = validate_agent_config("dependency_impact", {
    "max_total_tokens": 150_000,
    "timeout_seconds": 450,
    "provider_rate_limits": {"requests_per_minute": 10},
}, base=trusted_developer_config)
# Pass the returned real DependencyImpactConfig to DependencyImpactAgent(model, config).
```

The user validator rejects developer fields, including valid tool/prompt overrides,
agent-specific tuning and nested child envelopes. It applies only explicitly supplied
user edits over trusted defaults/config, preserves unedited nested quota values and
then validates the **complete runtime config**. `base` must come from trusted server
configuration, not from an end-user payload. Omitting a field preserves its current
value; explicit quota null disables that bound. The original base object is not mutated.

## Developer tooling (explicit)

```python
from config.agents.catalog import (
    describe_agent_config,
    validate_developer_agent_config,
)

details = describe_agent_config("dependency_impact", level="developer")
config = validate_developer_agent_config("dependency_impact", {
    "max_dependency_depth": 2,
    "max_context_characters": 120_000,
    "prompts": {"investigate": "Developer-authored investigation prompt"},
})
```

The explicit developer view describes the full runtime model, labels every field with
`field_levels`, and includes effective JSON Schema, defaults, groups, specific fields,
permitted prompt nodes, actual prompt defaults and the existing resolved model schema.
`describe_developer_agent_config` is also available directly. Developer validation uses
the complete agent class and its runtime validators. These Python helpers are not an
authentication mechanism; any future HTTP adapter must choose the appropriate entry point.

The catalog covers nine maintainability agents, three project-analysis agents,
functional adequacy and the security pipeline.
The latter's `OrientationLimits`, `ArchitectureLimits` and `ValidationLimits` are
**developer stage policy**: their user panel is empty because total tokens, deadlines
and provider admission belong to the existing repository execution envelope/model
gateway, not to those stage-limit classes. No unused runtime fields are added to them.

Research objectives, criteria, target paths and adaptability target context remain
request data. The developer descriptor publishes maintainability request schemas/defaults
separately. Existing model selection/sampling settings, credentials and API partial
overrides retain their existing model-client contracts. Credentials are never published
in either descriptor. This module supplies panel contracts, not a frontend or HTTP endpoint.

## Runtime semantics

Existing budgets/defaults remain: 100,000 context characters and 100,000 investigator
total tokens; 14 RPM / 250,000 TPM. Actual runtime allowance is still bounded by
repository/objective budgets, model caps and parent reservations. Provider-backed
calls share persistent rolling RPM/TPM admission by normalized provider/model,
including different credentials, concurrent audits, architecture stages, direct
execution and access probes. Concurrent policies use the strictest non-null bound;
a policy lease expires after 60 seconds without admission attempts. A caller using
null does not disable another active caller's bound. Anonymous offline model doubles
can still inject a local pacer and virtual clock.

Child envelopes, per-child tuning and model injection remain developer orchestration
policy. Editing a selected agent's user limits does not install a persistent override
store or rewrite the parent's child reservation policy. Coordinator direct tools and
unused inherited iteration fields remain hidden from developer form groups for legacy
compatibility, and are absent from the user view altogether.

## Verification

```powershell
uv run pytest src/test-agents/test_agent_config.py src/test-agents/test_agent_config_levels.py -q
```

Tests cover effective agent defaults, schema references, ownership/compatibility aliases,
strict user/developer separation, nested override preservation, explicit developer access
and actual graph consumption of a developer-validated config. Existing graph/E2E tests
verify the composed contracts against the established execution paths.

## Inventory across all implemented agent types

| Consumers | Configuration owner |
| --- | --- |
| All model-backed BaseAgent agents, including dummy and functional adequacy | `config/agents/model.py`: AgentSettings, ModelSettings; existing global prompt loader |
| Six maintainability investigators | Common execution classes; unique policy in local `config.py` where needed |
| Both coordinators and manager | Common coordinator family plus local contracts/presets; execution is in `src/server/runtimes/coordination/` |
| Three project-analysis stages | `config/agents/repository.py` and local stage-only specialization |
| Repository execution and every snapshot-bound agent's tools | `config/agents/repository_execution.py` and `config/agents/tools.py` |
| Both ProviderPacer and ModelGateway | `config/agents/provider.py`: ProviderRetryConfig; legacy explicit constructor overrides remain supported |

`provider_max_retry_wait_seconds` es una política de desarrollador (120 segundos por
defecto). Si un proveedor solicita una recuperación más larga, la etapa queda pendiente
con `provider_retry_wait_limit` y conserva el diagnóstico y los resultados parciales;
no se duerme durante horas ni se adelanta el reintento respecto a `Retry-After`.
Las esperas cortas de recuperación y la admisión local RPM/TPM conservan sus reglas.

`provider_recovery_budget_seconds` limita además la suma de esperas automáticas
de recuperación por invocación (60 segundos por defecto), tanto para errores
transitorios como para recuperación de cuota. Es independiente del tiempo activo
y nunca extiende una fecha límite absoluta. `max_provider_retries` admite cuatro
reintentos transitorios por defecto; las esperas exponenciales habituales son
2, 4, 8 y 16 segundos. Se siguen respetando los presupuestos de llamadas y tokens.
Para errores transitorios distintos de 429, primero se comprueba si queda un reintento
permitido y admisible por recursos, y solo entonces se autoriza su espera. Cinco 503
con la configuración predeterminada cierran con `provider_recovery_exhausted`: no se
atribuye el cierre a una sexta solicitud o una espera de 32 segundos que ya no estaban
permitidas. `provider_recovery_budget` corresponde a una espera que excedería el
presupuesto acumulado mientras todavía queda un reintento elegible. La recuperación
de cuota 429 conserva su política específica de admisión.
Los HTTP 503 se reintentan en la misma etapa, con el mismo estado y evidencia,
sin volver a planificar ni repetir lecturas. Si se agota la recuperación, la etapa
se conserva en `deferred_stages` con motivo `provider_recovery_exhausted` o
`provider_recovery_budget`; no se confunde con un error de esquema ni se cancelan
las investigaciones hermanas. No hay reanudación persistente después de reiniciar
el servidor: el resultado parcial documenta lo pendiente.

Si no se obtiene un plan válido, los investigadores pasan directamente a finalización
(o a su finalización limitada especializada). Investigación, evaluación y revisión se
declaran no iniciadas, sin incrementar `iterations` ni generar un fallo ficticio de
evaluación. El motivo original y los intentos del proveedor permanecen en el resultado.

La ejecución jerárquica distingue tres límites de tiempo, todos declarados una sola
vez y con los controles nuevos reservados al nivel desarrollador:

- `timeout_seconds`: tiempo activo del agente; la admisión de cuota puede pausarlo.
- `max_wall_time_seconds`: duración absoluta, incluidas todas las esperas (1800 segundos
  por defecto). La auditoría HTTP siempre establece este límite y los hijos heredan
  el más estricto entre su propio límite y el del padre.
- `provider_request_timeout_seconds`: plazo por intento al proveedor (90 segundos por
  defecto), acotado además por el tiempo restante. Se aplica al supervisor asíncrono,
  al transporte nativo cuando lo admite y al gateway de modelos del repositorio.

`cancellation_grace_seconds` limita la espera de confirmación de una cancelación
(2 segundos por defecto). Una limpieza que no responde queda supervisada en segundo
plano y no retiene indefinidamente al padre. Los ámbitos cancelados no pueden publicar
resultados tardíos. El cierre de clientes y la parada del servicio también tienen
esperas acotadas. Un intento que vence queda pendiente como `provider_request_timeout`;
no inicia nuevas solicitudes sobre una petición posiblemente aún viva.

El snapshot HTTP expone `activity`, `last_progress_at`, `active_seconds_remaining` y
`wall_seconds_remaining`. La actividad identifica agente, invocación, etapa, comienzo,
duración y cancelaciones pendientes; no incluye mensajes del proveedor ni credenciales.
Los hijos completados se validan, contabilizan y publican antes de esperar al resto;
la recopilación final conserva el orden de asignación y no vuelve a cobrar su consumo.
| Functional adequacy retrieval | `functional_adequacy/config.py`: embedding model and candidate count, actually consumed by retrieval |
| Security component, enrichment, DAST and remediation | One `security/config.py::SecurityConfig` instance; remediation uses the common ModelSettings; local prompt in `security/prompts/` |

Dummy has no unique tuning and therefore no redundant empty config class. Security's
scanner/patch-validation rule algorithms are implementation, not duplicate operating
budget definitions. Security credentials remain runtime/environment input, outside
descriptors. Its direct remediation client is still the existing OpenAI transport.

`ExecutionBudget` and `ToolLimits` are no longer defined in runtime implementation
files. Those modules retain aliases for compatibility. Shared config imports no agent
or runtime implementation. Agent request/result schemas and HTTP partial override
schemas are separate wire/data contracts, not alternate definitions of resolved agent
configuration. Repository envelope deadlines/objective caps and local stage limits
remain distinct nested allowances with their existing precedence.

The distribution packages both `src/server/` as `server` and the top-level `config/`
package. Shared imports are `from config.agents import ...` or `from config.agents.catalog import ...`.
Local agent policy is imported as `from .config import ...`, always a module rather
than a package. Local `dev-agents.yaml` presets are excluded from distributions.

### Coordinator and manager ownership review

Both dimension coordinators currently use the same operating defaults, quota controls,
delegation bounds, child envelope and synthesis node setting. Their different registries,
graphs and evidence semantics are code/request contracts, not unique configuration fields.
They therefore use `config.agents.CoordinatorConfig` directly without empty local classes.

The manager does have exclusive settings: `max_attempts_per_dimension`, its
`synthesize_assessments` prompt-node policy, hierarchy-level default budgets/bounds and
the coordinator-child envelope preset. They live in
`src/server/agents/maintainability/manager/config.py`, inheriting common declarations.
Any future coordinator-only setting belongs in that coordinator's own `config.py`,
not in this shared directory.
