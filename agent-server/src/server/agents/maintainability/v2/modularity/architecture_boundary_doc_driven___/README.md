# Architecture boundary doc-driven — planificación documental y estructural

Esta variante independiente de v2 acepta `AuditRequest.documented_architecture:
ArchitectureContextResult | None`. No registra ni integra participantes nuevos.
Sin documentación conserva el menú estructural. `documentation.py` añade semillas
`documented_boundary`, sin declarar conformidad ni incumplimiento.

## Integración documental (fase de planificación)

- La identidad documental del repositorio usa la misma función que el indexador
  (`identifier` de la ruta raíz resuelta); el commit debe coincidir exactamente con
  el snapshot. Un contexto incompatible no genera semillas documentales, pero no
  desactiva las estructurales. Un checkout trasladado necesita un nuevo contexto.
- La preparación es una puerta léxica conservadora, no una reevaluación semántica:
  revisa categoría, modalidad, certeza y texto del claim. `unspecified` no elimina
  una regla si su texto expresa imports permitidos, obligación o dirección normativa.
  Una autorización no prohíbe automáticamente las otras interacciones. Descripciones sin modalidad,
  propuestas, ejemplos y requisitos ajenos al dominio quedan diagnosticados. Los
  claims derivados y los afectados por incertidumbres/errores documentales no se
  convierten en obligaciones firmes. Un resultado parcial puede aportar claims
  válidos, pero nunca una especificación exhaustiva.
- El ID `document_claim_*` depende del contenido y procedencia, no del orden de
  entrada. `plan.document_claims` conserva cada claim original, todas sus citas,
  índice/repositorio/commit, secciones/rutas, estado, motivo, alcance localizado e
  IDs de oportunidades. Estos IDs no ingresan al ledger de evidencias de código.
- `document_mapping.py` distingue mapeos exactos, corroborados y ambiguos. Un sufijo
  documental como `shoplab/bootstrap.py` puede resolver `src/shoplab/bootstrap.py`
  únicamente cuando el índice respalda una raíz única. Las capas/grupos con nombre
  se resuelven solo desde descripciones explícitas de propiedad documental con
  procedencia consistente, nunca mediante convenciones de carpetas predefinidas.
  La dirección se obtiene del propietario anterior al verbo normativo, no de títulos
  que puedan mencionar ambos extremos. `section_paths` solo resuelve documentos, nunca código. Coincidencias
  ausentes/ambiguas quedan pendientes. No se asume implementación por certeza explícita.
- Se agrupan claims únicamente si coinciden el alcance indexado, declaraciones
  identificadas, propietario de proyecto y mecanismo de frontera (dependencia, encapsulación, composición,
  aciclicidad, integración). No se agrupan por categoría o carpeta documental.
  Un claim de alcance amplio puede producir semillas por proyecto independiente;
  si una relación interna resuelta conecta los proyectos, mantiene ambos extremos
  en una semilla interaplicación en lugar de separarlos.
  Los scopes amplios se particionan por pares de relaciones observadas y por grupos
  de declaraciones restantes, de hasta 12 archivos. Las rutas sin semilla verificable
  quedan en `unrepresented_paths`; referencias no resueltas quedan explícitas.
  Cada `portions` conserva alcance, relaciones y oportunidades que pueden cubrirla.
  La agrupación semántica de fronteras descritas con vocabularios distintos no está
  implementada: es preferible conservar referencias separadas a inventar equivalencias.
- Tras la deduplicación estructural se vinculan obligaciones pertinentes por mecanismo,
  propietarios, símbolos y relaciones dirigidas. El ciclo no se convierte en infracción.
  Si una semilla estructural cubre la misma obligación y porción, se reutiliza y se
  elimina solo esa referencia de la tarea documental equivalente. Las otras porciones
  continúan pendientes. Una tarea puede llevar múltiples claims y un claim múltiples tareas.
- El mismo selector LLM recibe ambos tipos de oportunidad y los claims completos
  de las documentales incluidas. No hay llamada clasificadora adicional, cuota mínima
  documental ni nuevos presupuestos. La deduplicación estructural no elimina tareas
  documentales por compartir archivos. Los límites de menú/contexto omiten tareas
  completas y conservan el registro original para diagnóstico. El prompt omite el
  registro operativo repetido de todas las particiones, no el claim ni sus citas.
  Una cita demasiado grande no expulsa una semilla estructural válida: se omite su
  vinculación documental del contexto y se registra la cobertura faltante.
- `investigation_coverage.documentation` cuenta recibidos, aplicables, agrupados,
  seleccionados, omitidos, no localizados, inciertos y no aplicables; conserva IDs
  pendientes y selecciones parciales. Los contadores de vinculados a estructuras y
  representados documentalmente son roles superpuestos, no cantidades sumables.
  Los contadores de claims usan IDs únicos aunque existan varias investigaciones.
  `pending_claim_ids` significa obligaciones aplicables no representadas íntegramente
  por la selección de sus porciones conocidas; excluye `not_applicable` y conserva
  claims seleccionados parcialmente. `pending_portions`, `unrepresented_paths` y
  `pending_information_claim_ids` permiten recuperar el alcance restante. Omitidos
  por menú/contexto se separan de candidatos simplemente no elegidos por el modelo;
  no se inventa que toda abstención sea falta de presupuesto.
  `fully_represented_by_selection` solo describe selección, nunca validación de la regla.
  `investigated` permanece en cero durante esta
  fase. La cobertura original de siete categorías no es cobertura de investigaciones.

El runner dedicado ejecuta el grafo normal completo:
`plan_investigation → investigate ↔ tools → synthesis → finalize`.
La finalización conserva candidatos sin revisión/confirmación, no findings definitivos.
`--plan-only` conserva el corte de verificación de planificación:

```powershell
uv run python -X utf8 src/test-agents/run_architecture_boundary_doc_driven.py "C:\repos\proyecto" --architecture-context "examples/shoplab/architecture_context.json" --output-file "investigation_doc_driven.json"
```

Carga la ruta indicada en `--architecture-context` como contrato canónico (no la
envoltura histórica de diagnóstico). Si el archivo antiguo tiene `state`, regenerarlo
con `run_architecture_context.py --output-file NUEVO_ARCHIVO.json`. No se migra ni
sobrescribe automáticamente. Las rutas relativas parten del directorio de ejecución.
Sin esta opción no se carga ningún archivo documental automáticamente; se conserva
`documented_architecture` si viene en `--request`. La opción CLI prevalece sobre ese campo.
El agente no carga archivos. `--output-file` sobrescribe un destino existente.
El grafo normal no se ha rediseñado; el runner dedicado ahora lo utiliza por defecto.
La resolución/confirmación de findings continúa fuera de este trabajo.

### Entrada sin prompts externos

El investigador no recibe prompts del usuario ni objetivos redactados por el
coordinador. `ArchitectureBoundaryRequest` acepta únicamente
`documented_architecture`, `targets`, `constraints` y una `continuation` estructurada
opcional. Los campos `objective`, `architectural_context`, `criteria`, `follow_up`,
`follow_up_diagnostics` o `prompt` se rechazan, incluso al invocar el agente directamente.
Los overrides `config.prompts` también se rechazan: se usan los Markdown internos.

El objetivo y los criterios que exige el runtime común son propiedades internas
de solo lectura, no campos de entrada. Planificación recibe ese objetivo interno,
alcance, restricciones, inventario y afirmaciones documentales. Investigación
recibe las tareas generadas por ese plan y la evidencia vigente. No se incorporan
objetivos originales/delegados ni contexto narrativo del llamador a los mensajes.
La documentación y las restricciones se tratan como datos, no nuevos prompts.

El coordinador conserva los objetivos externos en sus propios recibos, pero no
los reenvía a este investigador. Una continuación con un objetivo externo anterior
se rechaza explícitamente, sin convertirla en una investigación nueva.

### Presupuestos y consumo

La variante obedece exclusivamente `budgets_enabled` de `agent-server/launch.json`.
Con `true` se aplican los límites de tokens, llamadas, herramientas, tiempo y
recuperación. Con `false` se omiten esos cortes, también por tarea y en el ledger
del padre, pero el consumo real/estimado sigue contabilizado. No admite flags
`unlimited_*` locales. Pacing, cuotas RPM/TPM, cancelación, validez de los contratos
y validaciones de evidencia siguen activos. Los tamaños de salida soportados por
el proveedor no se convierten en ilimitados. Véase `server/agent_services/budgeting/`.
Los informes históricos de ShopLab conservan los límites usados en esas ejecuciones.

## Investigación documental

`document_investigation.py` resuelve exclusivamente `task.document_claim_ids` en
`plan.document_claims`. `execution.py` entrega `documentary_context` junto al contexto
técnico existente, sin inyectar el catálogo completo ni introducir otra llamada LLM.
Cada proyección incluye el claim original y citas literales, índice, secciones,
estado/motivo de mapeo, referencias no resueltas, exclusiones, porciones asociadas e
incertidumbres relevantes del `ArchitectureContextResult`. Se admite hasta un cuarto
del límite existente de contexto para esas proyecciones. Si no cabe un claim completo,
se registra como no disponible; no se recorta su cita ni se pierde en el plan.
Las inconsistencias de ID, procedencia, commit o secciones quedan explícitas.

`ClaimAssessment` añade `claim_id`, `status`, `rationale`, `code_evidence_ids`,
`scope_paths`, `exceptions_examined` y `limitations`. Los estados son `supported`
(compatible localmente), `contradicted`, `not_applicable` e `inconclusive`. Cada
conclusión conserva sus evaluaciones independientes. Un claim omitido por el modelo
queda inconcluso; nunca se interpreta como compatible. El host añade la limitación
de alcance local y advierte cuando no se registró comprobación de excepciones.
Los candidatos mantienen los `document_claim_ids` que fundamentan sus contradicciones.

La validación conserva todos los controles técnicos previos y añade pertenencia,
unicidad, evidencia fuente y procedencia por evaluación, inclusión de sus citas en
la conclusión y correspondencia de los claims contradichos con candidatos. Una
relación citada requiere fuente de ambos extremos también en la evaluación documental.
Los IDs documentales no son evidencia técnica. La reparación existente puede modificar
`code_evidence_ids`/`scope_paths` de `claim:<id>` y las referencias documentales de
candidatos existentes; no cambia estados ni reescribe narrativas. Si no puede repararse,
se cierra inconcluso. Las tareas sin documentación conservan la investigación code-first.

`investigation_coverage.documentary_investigation` es independiente de las métricas
de planificación, que no se modifican retroactivamente. Expone IDs seleccionados,
examinados con fuente citada, estados por investigación y porciones locales.
`unresolved_claim_ids` incluye inconclusos aunque tengan fuente; `pending_claim_ids`
identifica seleccionados todavía sin examen técnico validado. Un ID puede tener
distintos estados en tareas diferentes: no se suman esos conjuntos. Examinar una
porción nunca establece cobertura o conformidad completa del claim global.

La verificación real, sus IDs, evidencia, consumo y limitaciones están en
[INVESTIGATION_VALIDATION.md](INVESTIGATION_VALIDATION.md).

## Síntesis documental determinística

El nodo `synthesis` llama a `consolidate_candidates()` y, por separado, a
`consolidate_claim_assessments(results, plan, evidence)`. No usa LLM ni vuelve a
leer documentación o código. La consolidación de candidatos mantiene su contrato
de primer encuentro (el orden de prioridad de entrada importa), evidencia, orígenes,
colisiones, severidad y confianza. Solo se normaliza el conjunto de
`document_claim_ids` para comparar identidad, igual que los otros IDs técnicos;
su orden de presentación original no se modifica.

`BoundaryResult.documentary_synthesis` conserva por `claim_id` cada evaluación
original en un `LocalClaimAssessment` con ID estable e investigación de origen.
Su `assessment` reutiliza el contrato canónico completo, incluidos estado, razón,
fuente, alcance, excepciones y limitaciones. Las limitaciones de la investigación
también se conservan. El claim original, `KnowledgeEvidence`, índice y secciones
siguen en `plan.document_claims[claim_id]`: no se duplica el catálogo documental.

Los resúmenes tienen `has_contradiction`, `has_inconclusive`, investigaciones
seleccionadas/evaluadas y `coverage_status` limitado a `partial`/`not_evaluated`.
Nunca se declara cobertura completa o cumplimiento global. Las comparaciones
conservan los IDs de ambas evaluaciones: archivos o ventanas fuente disjuntos son
observaciones locales distintas; alcances y anclas técnicas iguales señalan una
posible incompatibilidad para revisión, no un conflicto lógico probado. Solapamientos
o anclas insuficientes conservan explícitamente la incertidumbre de comparación.
Las anclas de la investigación no se inventan como relaciones específicas del claim.

Se registran inconsistencias de catálogo, asignación, evidencia, scope y procedencia
sin borrar el original ni cambiar candidatos. Evaluaciones sin claim conocido
quedan en `unresolved_assessments`, no en un catálogo sintético. Repeticiones exactas
se agregan una sola vez; evaluaciones diferentes del mismo claim/tarea se conservan
con diagnóstico de multiplicidad. Los IDs de evaluación y el orden de la nueva
síntesis documental son independientes del orden de los resultados de entrada.

Para distinguir una evaluación real de un placeholder de ejecución se añaden dos
metadatos host, sin cambiar el razonamiento del investigador: `assessment_origin`
(`investigator`, `host_pending`, `unknown`) y `document_claim_delivery` por tarea.
Los placeholders de presupuesto/validación no cuentan como evaluación efectiva.
Una evaluación inconclusa explícita del investigador puede ser efectiva sin tener
fuente suficiente; se diferencia del subconjunto `source_examined_claim_ids`.
Los registros anteriores con fuente y procedencia válida conservan sus evaluaciones,
pero su entrega al prompt queda `unknown` si no existía recibo; no se reconstruye
artificialmente. Los metadatos del host no se aceptan como declaraciones del modelo.

`documentary_synthesis.coverage` contiene conjuntos de IDs únicos seleccionados,
entregados, entrega desconocida, evaluados, examinados con fuente, contradichos,
compatibles locales, no aplicables locales, inconclusos, seleccionados sin evaluar
y con cobertura parcial. Los roles se superponen y no deben sumarse. Las métricas
anteriores de planificación e investigación no se alteran. `exceptions_examined=[]`
sigue significando falta de comprobación registrada, no ausencia de excepciones.

Resultado de ShopLab y conteos antes/después:
[SYNTHESIS_VALIDATION.md](SYNTHESIS_VALIDATION.md).

### Verificación ShopLab (2026-11-07)

Se volvió a ejecutar el mismo repositorio/contexto con `gemini-3.5-flash-lite`,
sin modificar budgets. La selección del modelo puede variar; esta tabla compara
la reejecución base guardada con la última ejecución del código ajustado, ambas
con `termination_reason=planning_completed`. No es una medición de conformance.

| Medida | Base | Ajustado |
|---|---:|---:|
| Claims recibidos | 164 | 164 |
| No aplicables | 123 | 112 |
| Aplicables (incluye pendientes de localización) | 41 | 52 |
| Mapeados | 7 | 33 |
| Sin mapeo | 31 | 19 |
| Descartados por `scope_limit` | 3 | 0 |
| Semillas documentales antes de reutilizar estructuras | 6 | 67 |
| Oportunidades documentales tras equivalencias | 6 | 59 |
| Documentales seleccionadas | 2 | 3 |
| Estructurales seleccionadas | 10 | 9 |
| Estructurales seleccionadas con claims | 0 | 9 |
| Claims únicos seleccionados | 3 | 19 |
| Selecciones parciales de claims | no se distinguían correctamente | 15 |
| Claims investigados | 0 | 0 |
| Intentos de modelo contabilizados | 2 (incluye 503 y retry) | 1 |
| Tokens contabilizados | 23 691 | 20 656 |
| Tokens estimados incluidos en ese total | 16 309 | 0 |

La generación estructural permanece en 2 ciclos, 2 semillas de encapsulación y
16 de frontera de componentes antes de deduplicar. En el menú combinado se
enriquecen, antes de acotar el menú, 12 semillas estructurales con 16 claims distintos; los roles se superponen
con las oportunidades documentales y no deben sumarse. La selección final incluye
el ciclo `orders`/`inventory` con su prohibición documental y resuelve la ruta
`shoplab/bootstrap.py` contra el archivo real con prefijo `src/`.

Las tres reglas antes descartadas por tamaño quedan representadas y seleccionadas
parcialmente: independencia de Domain (4 porciones, 3 pendientes), independencia
de Application (4, 3 pendientes) y aislamiento Infrastructure/Presentation (2, 1
pendiente). Los 33 mapeos se reparten en 4 exactos y 29 corroborados. Los 19 claims
restantes no aportan un propietario localizable fiable: reglas generales como
"Source Dependencies" o "Feature dependency graphs", consumidores/callers sin
identidad de componente, procedimientos para emitir/verificar findings y excepciones
de tests fuera del alcance de producción. El JSON conserva sus motivos y referencias;
no se les asigna una ruta de código por aproximación textual.

Hay 48 obligaciones pendientes bajo la nueva definición: 15 seleccionadas solo
parcialmente y 33 sin selección completa (19 no mapeadas y 14 omitidas por menú).
El contador histórico de pendientes incluía además los no aplicables y no es
directamente comparable. No hubo omisiones adicionales por contexto en la ejecución
final. Se respetaron los límites existentes de menú e investigaciones: generar
porciones no garantiza que se seleccionen todas ni crea nuevas llamadas de clasificación.

Los JSON de verificación se guardaron fuera del repositorio, en
`C:\Users\Duck\AppData\Local\Temp\opencode\shoplab-planning-before.json` y
`shoplab-planning-verified.json`. La base guardó el reporte antes de fallar al imprimir
un carácter Unicode con CP1252; para la ejecución final se usó `python -X utf8`.
Hubo dos ejecuciones intermedias de validación adicionales: el total de las cuatro
ejecuciones reales fue 5 intentos y 85 374 tokens contabilizados, incluidos los
estimados del 503 inicial. Esta comparación no demuestra exactitud semántica
general del modelo ni cobertura completa de las reglas.

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

El único interruptor es global: `budgets_enabled`. Los campos numéricos de llamadas
y herramientas definen los cupos cuando está activado; ningún investigador puede
desactivarlos por su cuenta. Cuando está desactivado, también se omite el cupo
indirecto de pasos ligado al presupuesto de llamadas; las reglas de finalización,
falta de progreso y reintentos acotados no cambian.

Con presupuestos activados, los controles developer `max_tokens_per_investigation` (25 000) y
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
resueltas, sin alterar severidad, confianza o narrativa. `BoundaryFinding` usa el
contrato de candidato con evidencia, no el contrato de revisión de V1:
`validation_status` y `review_rationale` no existen ni se inventan durante el cierre.
Ningún candidato se acepta ni rechaza. Los detalles de límites, símbolos y relaciones
permanecen en `candidates`, junto a los estados nativos de `investigation_results`
y los dictámenes documentales en `claim_assessments`.

Coordinador y Manager V2 no interpretan aquellos atributos históricos. Una ejecución
con candidatos puede estar `completed` si terminó sin huecos: esto describe trabajo
terminado, no aceptación de hallazgos ni conformidad arquitectónica. La evidencia
inválida, los fallos y las conclusiones realmente inconclusas siguen siendo límites.
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

`uv run python src/test-agents/run_architecture_boundary_doc_driven.py RUTA` muestra el plan,
integraciones, referencias y diagnósticos legibles; `--output json` conserva JSON
canónico. Los helpers compartidos de otros runners conservan su comportamiento.
