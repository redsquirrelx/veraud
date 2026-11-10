# Architecture boundary — investigación y síntesis

Grafo actual: `START → plan_investigation → investigate ↔ tools → synthesis → finalize → END`.
Síntesis y finalización son deterministas, sin evaluación ni revisión adversarial
mediante otro LLM. Su pregunta es si una dependencia contradice
un límite razonablemente inferido del código y sus relaciones: dirección,
encapsulación o interfaces de integración. Cohesión/responsabilidades, impacto de
cambios, acoplamiento perjudicial, reutilización y corrección funcional de APIs
pertenecen a otros análisis.

## Oportunidades y selección

Reutiliza el snapshot accesible, símbolos, relaciones dirigidas y endpoints.
Los ciclos se calculan con el algoritmo existente, separando `type_only`.
Las etiquetas de API pública inferidas no tienen prioridad por su categoría.
Los imports internos ordinarios y la mera ausencia de aristas no generan tareas
para llenar cupos. Las carpetas no se convierten en reglas arquitectónicas.
Se mantienen la exclusión de tests/specs/fixtures/mocks y sus excepciones de alcance
explícito. Una relación legítima o un ciclo no son defectos automáticamente.

La configuración local `BoundaryConfig` añade controles **developer**:

- `max_planned_investigations`: objetivo máximo habitual **12**, configurable de
  1 a **15**. No es una cuota mínima.
- `max_integration_scan_files`: 60 archivos retenidos como máximo; 0 desactiva el
  escaneo (no los metadatos de endpoints disponibles).
- `max_integration_scan_characters`: 120 000 caracteres procesados como máximo,
  también acotados por el volumen permitido en el presupuesto de repositorio.

El menú y una selección no vacía cubren tanto límites internos por aplicación
como límites de integración disponibles; después completan por fundamento y
prioridad. Una integración no sustituye toda la cobertura interna de sus aplicaciones.
El modelo recibe IDs y resúmenes compactos, no todos los archivos, relaciones,
fragmentos o contratos completos de cada tarea. Las referencias completas quedan
en el resultado. Se respetan presupuestos compartidos, pacing, cancelación y retries.
Las consultas adicionales de metadatos siguen siendo opcionales y acotadas.

## Descubrimiento ligero de integraciones

`integrations.py` reutiliza AST de Python y los parsers tree-sitter existentes sobre
un conjunto acotado de código de producción, equilibrado por proyecto. Solo extrae
declaraciones y rangos: no ejecuta código ni realiza requests. No lee documentación
ni interpreta comentarios como arquitectura normativa.

Reconoce formas literales de `fetch`, axios y sus clientes, requests/httpx/aiohttp,
declaraciones de WebSocket y canales gRPC. Reutiliza rutas del índice y, como
fallback, rutas/listeners sencillos de Express/Fastify y listeners de uvicorn.
Las constantes de módulo y algunas construcciones de clientes permiten recuperar
bases URL; no se evalúa configuración arbitraria.

Solo vincula una aplicación destino como **candidata estructural** si coinciden
autoridad/puerto declarado, método y ruta y el destino es único. Conserva como
referencias los clientes, endpoints y declaraciones de listener, con archivo, hash,
líneas e IDs originales de endpoints cuando existen. Es una navegación verificable,
no una conexión de despliegue confirmada ni un hallazgo. Rutas relativas, múltiples
destinos o configuración dinámica quedan ambiguos. Una URL externa no se conecta
a una aplicación local solo porque coincida su ruta. Varios puntos de entrada del
mismo límite pueden agruparse; distintos límites no se colapsan por compartir app.

**Limitaciones:** el índice de imports no describe toda la comunicación. Montajes,
proxies, variables de entorno, aliases complejos, RPC/WS del servidor y wiring
dinámico pueden impedir identificar la integración. Los archivos omitidos por los
límites de escaneo y los fallos de parseo se reportan; ausencia de conexiones
identificadas no demuestra independencia.

## Contratos, diagnóstico y runner

`investigate` procesa las tareas secuencialmente. Un turno estructurado pide
consultas justificadas o cierra con `finding_candidate`, `no_finding` o
`inconclusive`. `tools` valida y normaliza las consultas y delega en el mismo
`RepositoryToolset`; no hay herramientas ni almacén de evidencias alternativos.
El estado local conserva índice actual, resultados, candidatos, consultas reutilizables,
evidencias y consumo. El avance tras el cierre no requiere otra decisión LLM.

Antes de la primera decisión, `tools` consulta la relación primaria planificada y
fragmentos de hasta 40 líneas en ambos extremos (hasta cuatro archivos de entrada).
La ubicación se apoya en evidencias/símbolos indexados, no en reglas por carpeta.
El catálogo del contexto separa IDs planificados de relaciones verificadas por
herramientas y relaciona cada archivo con sus IDs de evidencia fuente. Las demás
relaciones requieren su consulta indicada antes de poder citarse.

Los reintentos de procedencia usan el mismo cupo de correcciones, pero devuelven
parches solo para `components`, `evidence_ids`, `symbol_ids` o `relationship_ids`:
el host conserva la narrativa y revalida el resultado completo. La corrección
incluye el ID/campo incorrecto y referencias válidas, sin reenviar código ni
reconstruir candidatos enteros. Si falta fuente, se piden herramientas o se cierra
como `inconclusive`. No se corrigen ni aceptan automáticamente afirmaciones falsas.
El contexto elimina historiales, metadatos repetidos de procedencia y resultados
de tareas ajenas; el registro canónico conserva hashes, commit y snapshot. Los
rangos fuente ya recuperados también sirven para peticiones posteriores contenidas
en ellos, sin consultas ni nuevas referencias duplicadas.

Por defecto `unlimited_tool_calls=true` desactiva el límite de cantidad de llamadas
a herramientas del agente y su toolset de repositorio; el consumo se sigue contando.
`max_tools_per_investigation=null` desactiva también el cupo por tarea. No se usan
números artificialmente altos para representar ausencia de límite. Para volver a
limitar las llamadas, configurar `unlimited_tool_calls=false` y `max_tool_calls`;
se puede imponer además un `max_tools_per_investigation` numérico. Los demás agentes
mantienen `unlimited_tool_calls=false` por defecto.

También se desactivan por defecto los cupos de llamadas al modelo:
`unlimited_model_calls=true` y `max_calls_per_investigation=null`. El consumo
se sigue contabilizando. Para reactivarlos, usar `unlimited_model_calls=false`
y `max_model_calls`, y opcionalmente un `max_calls_per_investigation` numérico.
Los demás agentes mantienen sus límites de llamadas. El grafo no impone un
cupo indirecto de pasos basado en `max_model_calls` cuando este está desactivado;
tokens, tiempo, reintentos del proveedor y falta de progreso siguen acotando la ejecución.

Los controles developer `max_tokens_per_investigation` (25 000) y
`max_seconds_per_investigation` (60 segundos activos) acotan cada tarea. Además,
cada tarea recibe una parte de las llamadas/tiempo restantes. En tokens se usa
el consumo contabilizado para repartir el presupuesto, sin confundir la reserva
pesimista del siguiente request con consumo real. Los límites de admisión global
y configurado por tarea siguen siendo estrictos. Los
reintentos/correcciones también consumen su presupuesto. Las consultas idénticas
normalizadas reutilizan el resultado y sus IDs originales, incluso entre tareas;
dos rondas sin resultados nuevos detienen una investigación estancada.

Se requieren razones concretas para ampliar el alcance. Las lecturas están
acotadas a 60 líneas y los metadatos a 10 elementos como máximo por consulta,
sin ampliar los límites del toolset. Tests y documentación siguen excluidos por
defecto. No se aceptan cierres concluyentes basados solo en metadatos, símbolos
no inspeccionados, relaciones no recuperadas ni referencias inventadas. La
atribución a commit reutiliza las verificaciones del runtime; sin commit se
conserva únicamente la atribución a snapshot y hash de contenido.

`BoundaryResult.investigation_results` conserva los cierres originales, incluidos
`no_finding` e `inconclusive`. `synthesis` consolida únicamente candidatos con los
mismos campos sustantivos y sujetos; no fusiona textos parecidos, discrepancias
de severidad/confianza ni candidatos por compartir rutas o IDs. Une sus evidencias
y conserva en `candidate_origins` la investigación y el ID local de cada original.
Los IDs en conflicto se desambiguan determinísticamente sin eliminar candidatos.

`finalize` construye `findings` provisionales con el criterio y las referencias
resueltas, sin alterar severidad, confianza o narrativa. El contrato común no tiene
un estado «provisional»: se usa `validation_status="insufficient_evidence"` con una
justificación explícita de ausencia de revisión; ningún candidato se acepta ni
rechaza. Los detalles de límites, símbolos y relaciones permanecen en `candidates`.
Las hipótesis siguen vacías y `next_phase` queda en `null`. Se retienen el ledger
completo, las limitaciones, las métricas por investigación y el consumo por fase;
síntesis/finalización no consumen llamadas ni tokens. La ausencia de hallazgos no
prueba cumplimiento. Los resultados previos no sustituyen evidencia actual.

`BoundaryPlan` extiende el contrato común y conserva hipótesis vacías. Cada tarea
incluye alcance, pregunta neutral, hechos/inferencias, fundamento, evidencias,
estrategia y cierre independiente de encontrar un defecto. Los contratos históricos
y `investigation_tasks` se mantienen por compatibilidad; no se reutilizan como
prueba las conclusiones de una continuación previa.

`investigation_coverage` reporta producción/aplicaciones, relaciones internas y
entre aplicaciones, oportunidades por tipo/alcance, deduplicación, semillas
descartadas por calidad, límites de menú/contexto y descubrimiento de integraciones.
La selección informa IDs añadidos/eliminados y distingue sustitución/ampliación
de un simple reordenamiento. El estado del índice se separa del sesgo/presupuesto
de selección. Una investigación entre aplicaciones puede contarse en ambas.

`uv run python src/test-agents/run_architecture_boundary.py RUTA` muestra el plan,
integraciones, referencias y diagnósticos legibles; `--output json` conserva JSON
canónico. Los helpers compartidos de otros runners conservan su comportamiento.
