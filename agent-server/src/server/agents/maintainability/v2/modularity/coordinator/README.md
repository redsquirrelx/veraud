# ModularityCoordinator V2 — evaluación selectiva

`ModularityCoordinator.run()` ejecuta el grafo lineal completo:
`START → plan_assessment → delegate_investigations → collect_findings → finalize_assessment → END`.
Devuelve `AssessmentResult` tipado. Solo `plan_assessment` decide mediante LLM;
los otros tres nodos no hacen llamadas LLM ni investigaciones. Los investigadores
conservan sus propios grafos, herramientas y razonamiento. No se añaden ciclos,
revisión crítica del coordinador ni ejecución obligatoria del investigador disponible.
`plan_assessment()` sigue disponible como entrada pública de planificación aislada.

## Registro real

`registry.registered_investigators()` describe sin instanciar:

| ID | Implementación | Responsabilidad |
|---|---|---|
| `architecture_boundary` | V2 `architecture_boundary_doc_driven.ArchitectureBoundaryAgent` | Límites e interacciones, principios acotados y obligaciones documentales suministradas. |

**Solo está registrado `architecture_boundary`, variante documental V2.**
`responsibility` y `dependency_impact` no están disponibles: no se importan ni se
ejecutan sus implementaciones V1. No se modifican ni se borran esos investigadores.
El registro sigue el patrón existente de
`InvestigatorSpec(agent_class, request_class, result_class, capability)` con
`AgentCapability` compartido; añade tipos de problemas y restricciones derivadas de
los contratos/prompts reales. No registra las dos variantes de límites como tareas
separadas, evitando duplicar la misma especialidad.

El Manager V2 descubre `modularity` por defecto. `CoordinatorSpec` referencia
`ModularityCoordinator` y `AssessmentRequest`; la descripción pública se deriva
de los investigadores reales. Ni el registro HTTP ni el Manager V1 se modifican.
Descubrir una capacidad no ejecuta su clase. El Manager registra ahora el contrato
`AssessmentResult` como `result_kind="assessment"`; puede delegar, validar y recopilar
su resultado real, incluyendo los estados parcial, fallido o sin investigadores.
Un coordinador sin investigadores aplicables no cuenta como evaluación técnica del
Manager; los recibos originales quedan preservados.

## Entrada, salida y procedencia

`AssessmentRequest`: `objective` delegado, `original_objective` opcional para ejecución
independiente, `targets`, `constraints` y `repository_context`. Admite además
`documented_architecture`, `follow_up`, `follow_up_diagnostics` y `continuations`
por investigador. El estado conserva
request, repositorio, commit y snapshot sin duplicarlos en cada asignación.

`AssessmentPlan`: objetivo, `assignments`, requisitos no cubiertos y limitaciones.
Cada `InvestigationAssignment` conserva `investigator_id`, objetivo específico,
targets, restricciones y justificación vinculada a la solicitud. Queda disponible
en `state['plan']` para delegación. No implica ejecución ni cumplimiento por sí solo.

La selección y la complementariedad son decisiones del modelo, no reglas por
palabras clave. La validación comprueba IDs, rutas accesibles, frontera de targets,
restricciones y orden estable. Asignaciones exactamente repetidas se retienen una
sola vez; asignaciones diferentes no se fusionan por similitud. Se heredan targets
omitidos y todas las restricciones explícitas y de capacidad. Un plan vacío debe
explicar el motivo. Un error produce `plan=None` con motivo y limitaciones, nunca
un plan alternativo silencioso. Se preservan limitaciones y consumo incluso al fallar.

`capabilities=None` usa el registro real; una lista explícita permite reducirlo al
investigador documental o vaciarlo. Un ID no registrado se rechaza antes del LLM:
no se pueden reintroducir investigadores V1 mediante un override. No se amplía el
catálogo a partir de una respuesta del modelo.

Sin ruta explícita para Checkout, el objetivo y la justificación conservan ese
alcance semántico y `targets=[]`; no se inventa una ruta ni se descarta la solicitud.
Las fronteras verificables requieren `targets`; la fidelidad de restricciones solo
en prosa y la ausencia de redundancia semántica siguen dependiendo del LLM. No se
reanaliza código ni documentación para comprobarlas durante esta planificación.

## Invocación real y recursos

`dispatch.InvestigationDispatch` es una especialización del runtime existente
`CoordinatorExecution`, no un adaptador a un agente ficticio. Reutiliza reservas,
concurrencia acotada, herramientas por invocación, scopes del ledger de tokens,
plazos, pacing, cancelación, trazas y validación de resultados. Difiere la recolección
incremental del runtime al nodo `collect_findings`, sin ejecutar su síntesis LLM.
El snapshot compartido es inmutable; cada agente, request, toolset, cachés, evidencia
y contadores locales son independientes. Las cuotas y el transporte del modelo
compartidos son los del runtime común. Los cupos de llamadas/herramientas se adaptan
al sobre restante antes de reservarlos, sin subir los límites anteriores del rol.
La política de tokens del padre también se aplica al investigador documental.

Cada asignación resuelve `InvestigatorSpec.agent_class`, `request_class` y
`result_class` sin condiciones por nombre de investigador. La variante documental
usa una entrada exclusivamente estructurada: documentación, `targets`, `constraints`
y continuación opcional. No recibe el objetivo original, el delegado, contexto
narrativo ni compromisos textuales del llamador. Su objetivo de runtime es interno
y fijo; queda en `Assignment.question` para validar la respuesta, mientras el objetivo
externo permanece solo en `Assignment.source`, un recibo propio del coordinador.
La identidad viaja en el `RepositoryContext` real de la invocación.

Un alcance semántico conservado únicamente en la prosa de Checkout no se reenvía
como prompt ni se convierte en una ruta inventada. Para limitar al investigador se
deben suministrar selectores estructurados. El soporte de contextos textuales para
contratos genéricos permanece solo en pruebas, no en el registro de producción.

La documentación tipada se transmite nativamente al único investigador registrado,
la variante documental V2. El soporte de contratos genéricos textuales se conserva
solo como infraestructura, sin habilitar otros investigadores. No se truncan citas ni
restricciones para encajar ni se crea un contexto textual alternativo. El Manager puede recibir
`documented_architecture` y reenviarlo al coordinador.

`follow_up` y sus diagnósticos se conservan en el coordinador, pero no se reenvían
al investigador documental como instrucciones. `continuations[id]` se
valida y pasa únicamente si el request del investigador tiene `continuation`; el
investigador conserva sus verificaciones de snapshot, objetivo y compatibilidad.
Una continuación no soportada falla explícitamente, sin iniciar una investigación
nueva en su lugar. No se implementa una continuación/replanificación del coordinador.
Los resultados previos no se envían como evidencia al planner; solo se indican los
IDs que tienen continuación disponible.

Se retienen asignación original, request nativo enviado, presupuesto, resultado,
estado, consumo, duración y fallos. Dos requests nativos idénticos para el mismo
investigador no se ejecutan dos veces, aunque sus justificaciones difieran; queda
un recibo omitido explícito. Los errores individuales no borran hermanos exitosos.

## Recolección y resultado final

`collect_findings` usa el colector compartido con los esquemas reales de los
investigadores. Comprueba identidad, IDs, rangos/hash de evidencia y citas contra
el ledger ya disponible; no relee código para decidir conclusiones. Conserva
resultados completos `no_finding`, inconclusos y provisionales. Una respuesta inválida
queda en `execution_records` aunque no pueda formar un `InvocationRecord.result`
válido. No se convierte un candidato pendiente en un hallazgo aceptado.

`AssessmentResult` conserva request/plan, registro, asignaciones, respuestas crudas,
invocaciones, hallazgos consolidados, evidencia, relaciones, cobertura, limitaciones,
consumo y resumen. La agrupación es igualdad exacta de todos los atributos salvo
el ID superior: conserva todas las contribuciones originales, severidad, confianza
y limitaciones. El consolidado no contiene `validation_status` ni un dictamen de
revisión. Diferencias de confianza, estado nativo, texto, citas o alcance
impiden fusionar. Las relaciones entre investigadores indican solo componentes o
coordenadas de evidencia compartidas, nunca causalidad o conflicto lógico inferido.

La evidencia agregada se indexa por coordenadas del snapshot para evitar doble conteo;
los recibos completos siguen en las contribuciones e invocaciones. El consumo suma
el planner y cada invocación una sola vez. Si el proveedor registró más tokens que
los reportados por un investigador, se preserva el cargo observado, la advertencia
y el reporte original. Los fallos sin métricas usan la estimación conservadora
del runtime, marcada con `model_calls_estimated`.

Estados: `completed` solo si las asignaciones terminaron completas sin huecos;
`partial` si hay trabajo utilizable pero incompleto/inconcluso; `failed` si no hay
plan o resultados utilizables; `not_applicable` si el plan no eligió investigadores.
Una terminación del investigador no equivale a cobertura exhaustiva. Las rutas fuente
observadas y las invocaciones efectivamente evaluadas se informan por separado;
`global_compliance_established=false` permanece explícito. El resumen es una plantilla
determinística. `finalize_assessment` conecta directamente a `END`.

El cierre V2 no llama al clasificador heredado de V1 que interpreta
`validation_status` o `review_rationale`. Usa los estados de ejecución, los resultados
inconclusos nativos, la información faltante y la evidencia verificada. Encontrar
un candidato no convierte por sí mismo una ejecución completa en parcial, ni lo
promueve a aceptado. Los contratos y la revisión de V1 no cambian.

## Runner independiente

Desde `agent-server`, con el mismo YAML, credenciales y tracing de los otros runners:

```powershell
uv run python -X utf8 src/test-agents/run_modularity_coordinator_v2.py "C:\repos\ShopLab" --prompt "Investiga problemas arquitectónicos en Checkout" --output-file "modularity_assessment.json"
```

Opcionales: `--original-prompt`, `--target` repetible, `--constraint` repetible,
`--repository-context`, `--investigator` repetible para un subconjunto del registro,
`--no-investigators` para catálogo vacío, `--output json`, `--config`, `--agent-config`,
`--architecture-context` para un JSON canónico de `ArchitectureContextResult`.
Se imprime en consola y `--output-file` sobrescribe JSON UTF-8. Por defecto termina
en `finalize_assessment`; `--plan-only` mantiene el corte anterior sin investigaciones.

Las pruebas genéricas de varios participantes usan registros sintéticos exclusivos
de tests, sin importar implementaciones V1; no representan capacidades de producción.
Pruebas: investigadores simulados con requests reales, y jerarquía completa
Manager V2 → ModularityCoordinator V2 → ArchitectureBoundaryAgent documental real,
con repositorio Git y herramientas reales, usando un modelo offline determinístico.
Se comprueban tanto `no_finding` como candidatos provisionales sin promoverlos.
No se hicieron llamadas a un proveedor externo ni se requiere una clave para esos tests.
