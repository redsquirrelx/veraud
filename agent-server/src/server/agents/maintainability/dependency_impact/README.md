# DependencyImpactAgent

Investiga si las dependencias crean acoplamiento perjudicial para el mantenimiento,
dentro de modularidad de ISO/IEC 25010:2023. Reutiliza íntegramente el grafo LangGraph
de `agents/modularity_runtime/`, sin coordinadores, persistencia ni otro analizador.

## Ejecución (desde agent-server)

```powershell
uv run python src/test-agents/run_dependency_impact.py C:\repos\proyecto
uv run pytest src/test-agents/test_dependency_impact.py -q
uv run pytest src/test-agents -q
```

Proveedor/modelo de `config/dev-agents.yaml` (`agents.dummy` por defecto;
`--agent-config NOMBRE` para otra entrada). Clave `LLM_API_KEY` del `.env` de la raíz,
con precedencia de la variable de entorno. `--request` acepta un JSON
`DependencyImpactRequest`; `--config`, un JSON `DependencyImpactConfig`.

El ejecutor reutiliza el harness anterior, instancia solo este agente y aplica
`LangSmithTracingBackend` con span `dependency-impact`. `LANGSMITH_API_KEY` activa las
trazas; sin clave es no-op. Configurar `LANGSMITH_HIDE_INPUTS=true` y
`LANGSMITH_HIDE_OUTPUTS=true` para no enviar prompts/código/resultados a LangSmith.
Las pruebas son offline con modelos simulados y snapshots/herramientas reales.

## Investigación y validación

Planificación → ReAct/herramientas → evaluación → reinvestigación acotada o revisión
crítica → finalización determinística. Las mismas siete herramientas existentes
consultan archivos, símbolos, relaciones, fragmentos, texto, evidencias e infraestructura.
`list_relationships(source_id=...)` consulta salidas y `target_id=...` consumidores.
No hay una herramienta nueva de ciclos, métricas o transitividad: el LLM consulta
pocos pasos y el host valida rutas declaradas contra relaciones del snapshot.

`max_dependency_depth` limita las rutas aceptables (3 por defecto, configurable 1–8).
`max_relationships_per_assessment` limita relaciones por evaluación (12 por defecto).
Los presupuestos compartidos acotan llamadas, herramientas, contexto, tokens y tiempo;
el límite de profundidad también se comunica al modelo, pero no sustituye esos topes
de ejecución. No se carga un grafo completo en el historial ni se simulan cambios.

Contratos específicos separan dependencia estructural, análisis contractual y daño:
origen/destino, ID/tipo real de relación, ruta, escenario de cambio, consecuencia,
explicación de propagación, evidencia favorable/contraria, justificación e incertidumbre.
La clasificación distingue `demonstrated`, `plausible_risk`, `none` e `inconclusive`.
Un impacto demostrado requiere citas y justificación adicionales; no es un escenario
futuro renombrado. La revisión LLM cuestiona activamente esa distinción.

El host exige relaciones internas resueltas con endpoints/tipo exactos, inspección de
la declaración y ambos extremos, rutas conectadas/acotadas, citas verificables y un
escenario/consecuencia concretos. Los hallazgos deben enlazar todas las citas de las
evaluaciones. Métricas, ciclos, transitividad, interfaces o la mera existencia de una
dependencia no permiten aceptar un hallazgo por sí solos. Las observaciones basadas en
principios de diseño no se convierten en incumplimientos de reglas inexistentes.

## Resultados y limitaciones

`dependency_assessments` conserva dependencias normalizadas, rutas/ciclos comprobados,
consecuencias, riesgos, contraevidencia, incertidumbre y problemas de validación.
`components_investigated` resuelve rutas/nombres desde IDs reales. `findings` conserva
aceptados, rechazados e insuficientes: filtrar `validation_status == "accepted"`.
Se incluyen hipótesis descartadas, investigaciones inconclusas y consumo disponible.

Los IDs/citas se vinculan al snapshot y los bytes al commit cuando está disponible.
Una comprobación de procedencia no demuestra por sí sola causalidad semántica: esa
interpretación depende del LLM y de su revisión. La versión actual no host-verifica
relaciones externas/dinámicas o ausentes del grafo; quedan explícitamente inconclusas.
Imports no equivalen a llamadas runtime ni rutas estructurales a cascadas de cambios.
No se presume frecuencia histórica a partir del código. La política existente excluye
documentación narrativa: proporcionar criterios/contexto declarados como entrada.
El comportamiento compartido de `context_limit` y los agentes anteriores no cambia.

```python
agent = DependencyImpactAgent(chat_model, DependencyImpactConfig(max_dependency_depth=3))
result = await agent.run(fresh_repository_toolset, DependencyImpactRequest())
```
