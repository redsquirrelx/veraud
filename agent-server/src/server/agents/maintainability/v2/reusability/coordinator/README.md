# ReusabilityCoordinator V2

`ReusabilityCoordinator.run()` ejecuta el grafo lineal completo:
`START → plan_assessment → delegate_investigations → collect_findings → finalize_assessment → END`.
Devuelve `ReusabilityResult` tipado. Solo `plan_assessment` decide mediante LLM;
los otros tres nodos no hacen llamadas LLM ni investigaciones. No se añaden ciclos,
revisión crítica del coordinador ni ejecución obligatoria del investigador disponible.
`plan_assessment()` sigue disponible como entrada pública de planificación aislada.

## Registro real

`registry.registered_investigators()` registra `abstraction` y
`reuse_opportunity_doc_driven` con contratos V2. El segundo ejecuta solo
`plan_investigation`, con salida `planning_only`, sin findings ni evidencia; no
puede considerarse evaluación técnica completada. Ambos usan el patrón
`InvestigatorSpec(agent_class, request_class, result_class, capability)`.

Si el catálogo se vacía, el planner debe responder `assignments=[]` con una explicación en
`uncovered_requirements` o `limitations`; la validación rechaza un plan vacío sin
explicación. El resultado final es `status="not_applicable"` con planificación retenida,
sin hallazgos ni evidencia. Un coordinador sin investigadores aplicables no cuenta como
evaluación técnica del Manager; los recibos originales quedan preservados.

## Entrada y salida

`ReusabilityRequest`: `objective` delegado, `original_objective` opcional, `targets`,
`constraints`, `repository_context`, `documented_architecture` (solo reenviada a
investigadores que la declaren), `follow_up`, `follow_up_diagnostics`, `continuations`
e `investigator_selection` (filtro por el Manager según `maintainability_selection`).

`ReusabilityPlan`: objetivo, `assignments`, requisitos no cubiertos y limitaciones.
`ReusabilityResult`: request/plan, registro, asignaciones, respuestas crudas,
invocaciones, hallazgos consolidados, evidencia, relaciones, cobertura, limitaciones,
consumo y resumen determinista. La agrupación es igualdad exacta salvo el ID superior;
no hay `validation_status` ni revisión de aceptación.

Estados: `completed` solo si las asignaciones terminaron completas sin huecos;
`partial` si hay trabajo utilizable pero incompleto/inconcluso; `failed` si no hay
plan o resultados utilizables; `not_applicable` si el plan no eligió investigadores.
