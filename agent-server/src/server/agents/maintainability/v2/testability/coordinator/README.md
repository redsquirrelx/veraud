# TestabilityCoordinator V2

`TestabilityCoordinator.run()` ejecuta el grafo lineal completo:
`START → plan_assessment → delegate_investigations → collect_findings → finalize_assessment → END`.
Devuelve `TestabilityResult` tipado. Solo `plan_assessment` decide mediante LLM;
los otros tres nodos no hacen llamadas LLM ni investigaciones. No se añaden ciclos,
revisión crítica del coordinador ni ejecución obligatoria del investigador disponible.
`plan_assessment()` sigue disponible como entrada pública de planificación aislada.

## Registro real

`registry.registered_investigators()` registra `test_isolation` y
`test_controllability` (investigadores documentales
`TestIsolationAgent`/`TestControllabilityAgent`) con contratos V2:
`InvestigatorSpec(agent_class, request_class, result_class, capability)`.

Si el catálogo queda vacío, el planner debe responder `assignments=[]` con una
explicación en `uncovered_requirements` o `limitations`; la validación rechaza un
plan vacío sin explicación. El resultado final es `status="not_applicable"` con
planificación retenida, sin hallazgos ni evidencia. Un coordinador sin
investigadores aplicables no cuenta como evaluación técnica del Manager; los recibos
originales quedan preservados.

## Entrada y salida

`TestabilityRequest`: `objective` delegado, `original_objective` opcional, `targets`,
`constraints`, `repository_context`, `documented_architecture` (solo reenviada a
investigadores que la declaren), `follow_up`, `follow_up_diagnostics`,
`continuations` e `investigator_selection` (filtro por el Manager según
`maintainability_selection`).

`TestabilityPlan`: objetivo, `assignments`, requisitos no cubiertos y limitaciones.
`TestabilityResult`: request/plan, registro, asignaciones, respuestas crudas,
invocaciones, hallazgos consolidados, evidencia, relaciones, cobertura, limitaciones,
consumo y resumen determinista. La agrupación es igualdad exacta salvo el ID superior;
no hay `validation_status` ni revisión de aceptación.

Estados: `completed` solo si las asignaciones terminaron completas sin huecos;
`partial` si hay trabajo utilizable pero incompleto/inconcluso; `failed` si no hay
plan o resultados utilizables; `not_applicable` si el plan no eligió investigadores.

## Prompt de planificación

`prompts/plan_assessment.md` — excluyente de los hermanos; reescrito para el dominio
testabilidad (Question: ¿pueden los componentes aislarse de sus dependencias para
pruebas independientes?). Solo el planificador llama al LLM; las asignaciones se
validan determinísticamente contra el catálogo registrado.
