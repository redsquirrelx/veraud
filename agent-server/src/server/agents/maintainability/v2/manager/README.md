# MaintainabilityManager V2 — auditoría lineal

Esta es la implementación integrada de Maintainability en `quality-audit` y
`/api/audits`. Catálogo, despliegue e input web:
[integración V2](../../../../../../docs/maintainability-v2-integration.md).

Runner desde `agent-server`:

```powershell
uv run python -X utf8 src/test-agents/run_maintainability_manager_v2.py "C:\repos\ShopLab" --prompt "Investiga problemas arquitectónicos en Checkout" --output-file "manager_audit.json"
```

`--prompt` es obligatorio; `--target` y `--constraint` son opcionales y repetibles.
`--capabilities` acepta una lista JSON de capacidades públicas de coordinadores
realmente disponibles, con `id`, `agent_name`, `capability`, `problem_types` y
`constraints` (los dos últimos opcionales). Sin archivo usa el registro interno de
V2, que incluye `modularity`; un archivo con `[]` conserva la prueba de catálogo
vacío. No se cargan coordinadores V1 automáticamente. `--output json` muestra el resultado
completo. `--output-file` lo sobrescribe en UTF-8 incluso ante errores, conservando
los diagnósticos. El runner llega a `finalize_audit`; `--plan-only` mantiene el corte
anterior tras `plan_audit` sin delegaciones.

`run()` ejecuta `START → plan_audit → delegate_coordinators → collect_assessments →
synthesize_assessments → finalize_audit → END` y devuelve `AuditResult` tipado y
serializable. No hay ciclos, revisión crítica ni registro HTTP nuevo. Los nodos de
recolección, síntesis y finalización no llaman al LLM ni consultan herramientas.

El Manager V2 no interpreta los campos históricos `validation_status` ni
`review_rationale`. El investigador documental ya no los emite y el consolidado
del coordinador no los declara. Se conservan los estados nativos inconclusos,
fallos, limitaciones y comprobaciones de evidencia/procedencia. `completed` describe
ejecución terminada, nunca aceptación automática de candidatos o conformidad global.

```python
manager = MaintainabilityManager(model, tracing_backend=tracing)
result = await manager.run(
    tools,
    MaintainabilityRequest(
        objective="Investiga problemas arquitectónicos en Checkout",
        targets=["src/checkout"],
        constraints=["No modificar archivos"],
    ),
)
print(result.status, result.summary)
```

El catálogo usa `CoordinatorCapability`: reutiliza
`AgentCapability` del runtime compartido (`id`, `agent_name`, `capability`) y añade
tipos de problemas y restricciones. No instancia participantes. Acepta cero, uno o
varios coordinadores y rechaza IDs repetidos. Por defecto `registered_coordinators()`
describe el coordinador `modularity`, con referencias a su clase y request real.
Sus capacidades y restricciones se derivan del registro de investigadores del
coordinador, no de nombres fijados en el prompt del Manager. Pasar `capabilities=[]`
produce un catálogo vacío; una lista explícita sustituye el predeterminado.
El coordinador reutiliza investigadores reales sin alterar su lógica. No se cambia
el registro HTTP, el Manager V1, el prompt de `plan_audit` ni se ejecuta el coordinador
durante el descubrimiento. El coordinador de modularidad V2 ejecuta ahora su flujo
completo y únicamente los investigadores seleccionados por `plan_assessment`.
Su registro de producción contiene **solo `architecture_boundary`, variante
`architecture_boundary_doc_driven` de V2**. El catálogo del Manager se deriva de
esa única capacidad; no anuncia ni ejecuta Responsibility/DependencyImpact V1.

`plan_audit` usa `InvestigationExecution.call` para salida estructurada Pydantic,
pacing, presupuestos, errores de proveedor, límites por llamada y contabilidad.
No habilita herramientas ni añade ciclos. Las correcciones de formato compartidas
están desactivadas por defecto (`max_schema_retries=0`); pueden configurarse con el
control existente, sin crear un ciclo de planificación del dominio.

La validación posterior comprueba catálogo y rutas accesibles; rechaza ampliaciones
fuera de `request.targets`, hereda targets si el modelo omite scope, preserva todas
las restricciones explícitas y las del coordinador, elimina duplicados exactos y
ordena las asignaciones de forma estable. Objetivos o razones diferentes nunca se
fusionan por similitud. El request original permanece sin cambios en el estado y
es la procedencia común de todas las asignaciones; el objetivo del plan puede ser
una interpretación del LLM, sin reemplazar el prompt original.

Un plan vacío necesita explicación en `uncovered_requirements` o `limitations`.
Una respuesta inválida o una infracción de integridad produce `plan=None`, motivo
de terminación y limitaciones explícitas; no se ejecuta nada como fallback. Las
limitaciones originales del modelo y los consumos se conservan. El plan queda en
`state["plan"]` para `delegate_coordinators`.

## Compatibilidad de ejecución por nodos

```python
state = await manager.plan_audit(tools, request)  # Solo el planner, como antes.
if state["plan"] is not None:
    state = await manager.delegate_coordinators(tools, state)
records = state["coordinator_results"]  # Salida cruda sin recolección ni síntesis.
```

El método público invoca únicamente el nodo de ejecución homónimo. Consume el plan
sin reinterpretar objetivos ni llamar al LLM para delegar. Resuelve `CoordinatorSpec`
por ID, construye su `request_class` real y llama a `agent_class.run(child_tools,
request)`. La identidad del repositorio/commit/snapshot viaja mediante el contexto
de herramientas real, como exige la interfaz de `ModularityCoordinator`; no se
añaden campos ficticios a su request. Se preservan objetivo delegado, prompt original,
targets, restricciones explícitas/de capacidad y contexto del repositorio.

`CoordinatorExecutionRecord` conserva ID estable de asignación, asignación original,
request enviado, presupuesto reservado, estado, resultado completo serializable,
consumo, limitaciones, fallo seguro, evidencia recuperada y duración. Los resultados
permanecen en el orden del plan, independientemente del orden de finalización.
Un duplicado exacto se registra como omitido y no se ejecuta dos veces. Una asignación
inválida o un ID inexistente no impiden ejecutar hermanos válidos. No se modifica el
plan original ni se descartan silenciosamente respuestas inválidas.

Se verifica la correspondencia de repositorio, revisión y solicitud de las respuestas;
un resultado incoherente se conserva con estado fallido, no como assessment válido.
`CoordinatorSpec.result_kind="planning"` sigue disponible para participantes que solo
planifican: sus salidas permanecen parciales aunque declaren `completed`. Modularidad
usa ahora `result_kind="assessment"` con su contrato real `AssessmentResult`.
Un plan fallido produce estado fallido y mantiene el resultado/diagnóstico original.
`delegation_status` describe solo la delegación (`not_required`, `completed`, `partial`,
`failed`), nunca la finalización de la auditoría. Un plan vacío no ejecuta nada.

Se reutilizan los controles compartidos de `CoordinatorConfig`: `max_parallel`,
`max_invocations`, `invocation_limits` e intervalo de inicio, sin aumentar los valores
predeterminados anteriores de llamadas, herramientas, tokens o tiempo del Manager.
Se reserva una cuota de llamadas/herramientas por hijo antes de ejecutarlos; el mínimo
de cuatro llamadas por sobre coincide con la admisión del runtime existente. Los
límites de tokens usan scopes del ledger compartido y los plazos se bifurcan del
plazo original. Cada invocación tiene agente, request, snapshot, herramientas, cachés,
evidencia y presupuesto local independientes. Solo se comparten infraestructura
protegida de cuotas, retrieval, trazas y cliente del modelo, como en el runtime común.

Los consumos se agregan sin perder los originales de cada resultado. Si una excepción
impide devolver métricas, se conserva el cargo de tokens observado en el ledger y
una estimación conservadora de llamadas (`model_calls_estimated=true`), en lugar de
fingir coste cero. Se reutilizan pacing, plazos/cancelación acotados,
`observe_invocation`, `wrap_stage` y `ExecutionFailure`. La entrada explícita
`delegate_coordinators()` sigue ejecutando únicamente ese nodo. El flujo completo
se utiliza mediante `run()`.

## Recolección y síntesis determinísticas

`collect_assessments` conserva los recibos originales sin cambios y produce
`CollectedAssessment` por asignación. Comprueba asignación, registro, request y
repositorio/commit/snapshot; usa el esquema real declarado cuando existe. Valida
evidencias contra los IDs, hashes, rutas y líneas del snapshot ya disponible, sin
releer archivos ni revalidar semánticamente el código. La procedencia de contribuciones
consolidadas se comprueba contra los resultados de sus invocaciones. Un fallo no se
rehabilita a partir de su payload. Los datos inválidos permanecen en el recibo crudo,
con `AuditIssue` explícito. Un recibo repetido se evalúa una sola vez; recibos distintos
con el mismo ID se consideran ambiguos. También se detectan recibos faltantes o ajenos.

Se admiten hallazgos directos (`findings`) y el contrato existente
`consolidated_findings` con sus contribuciones anidadas. No se vuelven a contar esas
contribuciones como hallazgos independientes. `AuditFinding.payload` conserva todos
los campos originales: severidad, confianza, estado, evidencia, excepciones y límites.
`FindingOrigin` enlaza ID original, coordinador, asignación y ubicación del hallazgo.
Las evidencias reciben claves locales namespaced, conservando sus IDs originales.

`synthesize_assessments` fusiona solo payloads idénticos salvo el ID superior, con
recibos de evidencia completos idénticos y sin problemas de integridad del hallazgo.
Conserva todos los orígenes. Diferencias de severidad, confianza, estado o cualquier
otro atributo impiden la fusión. No se normalizan semánticamente textos ni se promedian
confianzas. Los datos sin prueba suficiente no se fusionan entre orígenes distintos.
La presentación ordena por severidad declarada sin modificarla.

`FindingRelation` identifica únicamente anclas verificables compartidas: componentes
reales, referencias a relaciones del snapshot y evidencia de las mismas coordenadas.
`interpretation=shared_anchors_only` no afirma causalidad, equivalencia o contradicción.
Compartir archivos nunca basta para deduplicar; con un único hallazgo no se inventan
relaciones. Se preservan requisitos no cubiertos, cobertura reportada e inconclusos.

`AuditCoverage` distingue asignaciones seleccionadas, evaluadas, completas, parciales,
fallidas y no ejecutadas, más rutas de fuente observadas. Los planes de investigadores
no cuentan como evaluación técnica. `global_compliance_established` siempre es falso.
No existe una regla de cobertura exhaustiva global. Las métricas agregadas proceden
de la delegación: estos tres nodos no las vuelven a sumar ni añaden el consumo de
investigadores anidados a los totales que ya incluyen sus coordinadores.

## Resultado final y límites

`AuditResult` contiene request y plan originales, catálogo, recibos completos,
assessments recopilados, hallazgos, evidencia, relaciones, cobertura, diagnósticos,
consumo, duración, transiciones y resumen determinístico en español. Sus referencias
se validan al serializar/deserializar mediante el contrato Pydantic. Es el contrato
local V2 exportado para consumidores; no se cambian endpoints ni frontend V1.

- `completed`: todas las asignaciones seleccionadas terminaron completas, sin
  inconsistencias o requisitos/inconclusos pendientes. Describe esa ejecución,
  **no** una prueba de mantenibilidad o cobertura exhaustiva del repositorio.
- `partial`: hay trabajo utilizable pero también planificación solamente, fallos,
  observaciones inconclusas o problemas de integridad.
- `failed`: no hubo plan válido ni evaluación utilizable de las asignaciones.
- `not_applicable`: el plan válido no seleccionó coordinadores; no se evaluó el código.

`ModularityCoordinator` devuelve ahora `AssessmentResult` completo. Si termina parcial,
fallido o sin investigadores aplicables, el Manager conserva ese estado y no fabrica
findings. Las continuaciones y la investigación técnica permanecen en los
investigadores. Hay pruebas con coordinadores simulados y con la jerarquía real V2
hasta el investigador documental, usando modelo offline. La validación de referencias es
de integridad y procedencia del snapshot; no sustituye una revisión técnica ni certifica
que el razonamiento del productor sea suficiente. `finalize_audit` conecta directamente
con `END`, incluso en ejecuciones parciales, vacías o fallidas.

## Límite de la validación determinística

La relevancia de capacidades y las restricciones expresadas solo en lenguaje
natural son decisiones del LLM. No se intenta validarlas por palabras clave ni
inferir rutas de nombres de componentes. Para una frontera de acceso verificable,
el llamador debe proporcionar `targets`; el prompt exige conservar también el
alcance en prosa y señalar localización ambigua. Un plan no constituye evidencia
de cumplimiento o de problemas técnicos.

## Modos de selección del coordinador

**Modo actual — selección determinista.** `maintainability_selection` lo aplica el
Manager de forma determinista: ve un catálogo de coordinadores recortado a lo
seleccionado (o a los registrados si no hay selección), la instrucción
`Ejecución determinista` del objetivo refleja exactamente lo seleccionado, y el
planner no recibe el campo `maintainability_selection` (solo lo consume la
delegación para propagar `investigator_selection`). Un plan que asigne un
coordinador no seleccionado se rechaza como `unknown_coordinator` en
`validate_plan` y el nodo de delegación no ejecuta nada fuera del catálogo. Con la
semántica actual, `maintainability_selection = None` conserva el catálogo completo
(compatibilidad con llamadas directas); selección `{}` sigue rechazada por la
validación de entrada del pipeline.

**Modo previo (prompt-guided) — solo comentado.** La versión anterior dejaba el
catálogo completo al planner y dependía de que el LLM respetara la selección
(instrucción `Coordinadores a ejecutar` en el objetivo + catálogo entero en el
contexto). Nada garantizaba determinismo: un assignment al coordinador
desseleccionado era válido y se ejecutaba con todos sus investigadores.

Para volver al modo previo, sustituir en este directorio:

1. `manager/execution.py` — en `initial_state()`, restaurar
   `coordinator_catalog()` (el comentario LEGACY queda sobre la línea nueva);
   en `_context()`, quitar `"maintainability_selection"` del `exclude`.
2. `manager/agent.py` — restaurar `coordinator_catalog(capabilities)` en `run()`
   y `plan_audit()` en vez de `selected_coordinators(...)`, devolver
   `deterministic_objective` a la implementación completa comentada en la cabecera
   del archivo, y restaurar el import de `coordinator_catalog`.
3. `manager/registry.py` — `selected_coordinators()` puede quedar pero deja de
   usarse (o eliminarlo).

Puntos de verificación al cambiar de modo: `test_maintainability_selection*.py`,
`test_maintainability_v2_plan_audit.py`, `test_maintainability_v2_delegation.py`
(los tests del planner asumen selección determinista); el contexto del planner se
afirma como `request.model_dump(exclude={...})`.
