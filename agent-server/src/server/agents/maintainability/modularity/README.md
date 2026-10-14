# ModularityAgent

Coordinador LangGraph de solo lectura en `maintainability/modularity/`. No
reimplementa investigadores ni introduce persistencia o un framework adicional.

## Integración verificada

Los tres contratos existentes son:

| Implementación (relativa a `src/server/agents/`) | Entrada | Salida |
| --- | --- | --- |
| `maintainability/architecture_boundary/agent.py`: `ArchitectureBoundaryAgent` | `AuditRequest` | `AuditResult` |
| `maintainability/responsibility/agent.py`: `ResponsibilityAgent` | `ResponsibilityRequest` | `ResponsibilityResult` |
| `maintainability/dependency_impact/agent.py`: `DependencyImpactAgent` | `DependencyImpactRequest` | `DependencyImpactResult` |

Todos exponen `await agent.run(repository_toolset, request)` y comparten
`modularity_runtime/`. `registry.py` mantiene sus clases, capacidades y tipos;
no es el registro HTTP `app/agent_registry.py`, cuyo contrato exige `BaseAgent`.
No se registra una integración HTTP incompatible ni se modifica su infraestructura.

Uso programático: `await ModularityAgent(model, config).run(fresh_tools, request)`.
El modelo nativo (o wrapper `.llm`) y sus clientes pertenecen al llamador. Se
pueden inyectar `tracing_backend` y `investigator_factory(id, model, limits)`.
La fábrica debe conservar los contratos y las garantías de validación de los
investigadores reales; no es una frontera contra implementaciones maliciosas.

## Grafo y rutas

`plan_assessment → delegate_investigations → collect_findings → synthesize_findings
→ decide_next_step`.

- `reinvestigate → plan_targeted_follow_up → delegate_investigations`.
- `finalize → finalize_assessment → END`.
- `finalize_limited → finalize_assessment → END`, con motivo explícito.

El plan inicial es determinístico: alcance y pregunta especializada para los tres
investigadores. La síntesis usa structured output nativo y corrección acotada del
runtime existente; su prompt reside en `prompts/synthesize_findings.md`.
Propone agrupaciones, lagunas y resoluciones, pero no gobierna el router.
La decisión consulta estado estructurado, límites y equivalencia de solicitudes.
El seguimiento llama solo a los investigadores pertinentes. Solicitudes idénticas
pendientes se agrupan; una solicitud completada no se repite sin evidencia fuente
nueva (otro ID de recuperación de los mismos bytes/líneas no cuenta).

## Estado, evidencia y completitud

Cada invocación tiene UUID propio, ronda, investigador, pregunta, alcance, referencias,
presupuesto reservado, resultado especializado completo o error seguro, duración y
consumo. Nunca se sobrescribe un resultado por llamar otra vez al mismo investigador.
Se espera a todos los resultados terminales de cada ronda antes de sintetizar.
Se conserva evidencia recuperada incluso en invocaciones fallidas o con timeout.

Solo se consolidan hallazgos `accepted`. Se conservan sus contribuciones originales,
criterios, citas, símbolos, commit, snapshot y limitaciones. Rechazados e inconclusos
permanecen en los resultados de invocación. No se generan puntuaciones; la confianza
no se combina numéricamente. Diferentes preocupaciones no se fusionan por compartir
archivos. Las contradicciones reconocidas mantienen hallazgos `disputed`, sin severidad
ni confianza agregada. Una resolución exige investigación dirigida completada y
referencias de fuente de esa invocación; las contradicciones requieren retirar
explícitamente conclusiones refutadas, conservándolas en los registros históricos.

- `completed`: investigadores esenciales completados y sin lagunas materiales.
  No significa que el repositorio sea modular ni una certificación exhaustiva.
- `partial`: existen resultados utilizables, pero faltan evidencia, investigaciones
  esenciales, síntesis válida o resolución de contradicciones.
- `failed`: ninguna investigación produjo un resultado utilizable.

Una lista vacía de hallazgos no prueba cumplimiento. Los resultados parciales nunca
se transforman silenciosamente en conclusiones favorables.

## Recursos, seguridad y observabilidad

Se comparten snapshot inmutable y cliente de modelo; cada invocación obtiene un
`RepositoryContext` y `RepositoryToolset` nuevo, con la política de acceso existente.
No hay herramientas de escritura. Se usan todas las herramientas de investigación
existentes, no herramientas nuevas del coordinador. Documentación arquitectónica y
criterios deben declararse como entrada, conforme a la política actual.

Antes de despachar en paralelo se reserva la envolvente completa de llamadas,
tokens y herramientas de `invocation_limits`. Rigen además los mínimos entre
presupuesto global del repositorio y configuración, tiempo global, rondas y número
de invocaciones. El cupo global de caracteres recuperados se divide conservadoramente
entre `max_invocations`. Los fallos sin métricas se cobran por la reserva completa y
se marcan estimados. La síntesis consume el mismo presupuesto global. La concurrencia
se limita con semáforo (`max_parallel=1` para adaptadores no seguros concurrentemente).
La cancelación del llamador se propaga; no se convierte en un informe completado.

`investigation_start_interval_seconds` pertenece a `ModularityConfig` y separa los
arranques reales de investigadores, sin serializar su trabajo posterior. Su valor
predeterminado es 0 (compatibilidad); el regulador se comparte entre rondas, respeta
el semáforo, el plazo global y la cancelación. Una asignación cuyo plazo vence antes
del arranque queda `skipped`, sin cobrar la reserva de una investigación no iniciada.
Este retraso es independiente del intervalo entre solicitudes al proveedor.

El runtime comparte un `RequestPacer` entre los investigadores y la síntesis: respeta
el enfriamiento del proveedor, incluido `Retry-After` y `google.rpc.RetryInfo` a través
de las excepciones encadenadas del adaptador Google. Se reintentan solo errores
transitorios (429, ciertos 5xx y transporte), hasta `max_provider_retries=2` por llamada
lógica. Cada intento cuenta como llamada y reserva tokens; siguen vigentes todos los
límites y la cancelación. `provider_request_interval_seconds` (predeterminado 0) y
`provider_retry_backoff_seconds` (predeterminado 2) permiten ajustar el ritmo. Una cuota
diaria agotada no se puede reparar con reintentos: la ejecución termina con limitaciones.
Errores permanentes 400 no se reintentan ciegamente.

Además, `provider_rate_limits` aplica por defecto **14 RPM** y **250.000 TPM** en una
ventana móvil de 60 segundos, compartida por investigadores y síntesis. También aplica
a investigadores independientes. Cada intento reserva entrada estimada más salida
máxima, y se reconcilia con el uso reportado; si no hay métricas, mantiene la reserva.
La espera combina cuota, intervalo fijo y cooldown, respeta cancelación y timeout, y
registra `provider_rate_limit_wait`. Si una sola solicitud no cabe en el TPM, termina
con `provider_tpm_request_limit` sin enviarla. Los presupuestos totales no cambian.

```json
{
  "provider_rate_limits": {
    "requests_per_minute": 14,
    "tokens_per_minute": 250000
  }
}
```

La configuración superior del coordinador gobierna la cuota compartida; no hay una
cuota independiente para cada subagente delegado. `null` desactiva explícitamente un
límite (usado en pruebas offline); la prueba live los mantiene activos. Las cuotas
locales no conocen otros procesos o clientes usando el mismo proyecto de Google.
Para compartir entre evaluaciones del mismo proyecto/modelo, inyectar la misma
instancia de `modularity_runtime.provider.ProviderPacer` mediante `provider_pacer`
en agentes/coordinadores del mismo event loop. No hay persistencia entre procesos,
consultas a la cuota real del proveedor ni límite RPD. Las estimaciones de tokens
y diferencias de contabilidad del proveedor no garantizan eliminar todos los 429.

La síntesis envía un esquema nativo simplificado, sin cotas de longitudes/tamaños que
pueden aumentar la complejidad de generación de Gemini. Tipos, enum, campos requeridos
y referencias se mantienen; todas las restricciones originales se validan localmente
con Pydantic. No se degrada a texto sin validar. Los diagnósticos incluyen códigos HTTP
y categorías saneadas, nunca el mensaje bruto del proveedor. Un fallo transitorio de
síntesis puede recuperarse en una ronda posterior, sin reiniciar contadores ni plazos;
un fallo permanente no se borra. No se asume que todo error 400 sea de esquema.

`get_logger` registra nodos y resultados sin código ni credenciales. Cada llamada se
envuelve con `TracingBackend.wrap_stage`, UUID y ronda; los grafos y llamadas nativas
heredan el tracing LangGraph/LangChain. `LangSmithTracingBackend` es el predeterminado;
sin clave es pass-through. Para no subir entradas/salidas, configurar
`LANGSMITH_HIDE_INPUTS=true` y `LANGSMITH_HIDE_OUTPUTS=true`.

## Ejecución y pruebas

Desde `agent-server`:

```powershell
uv run python src/test-agents/run_modularity.py C:\repos\proyecto
uv run pytest src/test-agents/test_modularity.py -q
uv run pytest src/test-agents/test_modularity_e2e.py -v -s
uv run pytest src/test-agents tests/test_pipeline_ports.py -q
```

El runner reutiliza el harness existente: `LLM_API_KEY` de `.env`, proveedor/modelo
de `config/dev-agents.yaml` (`--agent-config dummy` por defecto), y soporte LangSmith.
`--request solicitud.json` y `--config limites.json` aceptan contratos validados.

Ejemplo de `limites.json` para hasta tres investigaciones concurrentes, con arranques
escalonados y menor separación entre peticiones (misma política que usa la prueba live):

```json
{
  "max_parallel": 3,
  "investigation_start_interval_seconds": 1,
  "provider_request_interval_seconds": 0.5,
  "provider_retry_backoff_seconds": 5
}
```

```powershell
uv run python src/test-agents/run_modularity.py C:\repos\proyecto --config limites.json
```

La política la ejecuta el coordinador; el runner y la prueba solo suministran valores.
`Retry-After` y los enfriamientos por cuota pueden imponer esperas mayores que 0,5 s.

Las E2E usan el registro predeterminado, los tres investigadores, grafos y herramientas
reales; solo el transporte del modelo está simulado. Una fixture de arquitectura conocida
permite verificar un hallazgo aceptado, sus citas, una finalización de una ronda, un
seguimiento dirigido de dos rondas con evaluación de responsabilidad source-backed,
lagunas no resueltas y fallos del proveedor sin perder hallazgos previos. También verifican
identidad de invocación/trazas y hashes de todos los archivos antes y después.

Con `-v -s` se ven nombres de escenarios y progreso en vivo por investigador (inicio,
resultado recibido y motivo de terminación). Al finalizar se muestran los estados reales
por ronda, UUID abreviado, herramientas, llamadas LLM, tokens, duración, seguimiento,
hallazgos, lagunas pendientes y nodos ejecutados. Se distingue el estado de la evaluación
del resultado de pytest. El reporter solo observa las fronteras de tracing existentes;
no sustituye agentes ni modifica el flujo. Con `-q` sin `-s`, pytest captura esta salida
de forma normal; `--capture=tee-sys` permite verla y conservarla capturada.

Prueba con proveedor real, opcional y con coste (no se activa por tener credenciales):

```powershell
$env:MODULARITY_E2E_LIVE = "1"
uv run pytest src/test-agents/test_modularity_e2e.py -q -k live -s
Remove-Item Env:MODULARITY_E2E_LIVE
```

Usa `.env` y YAML del harness existente; `MODULARITY_E2E_AGENT_CONFIG` selecciona la
entrada (por defecto `dummy`). Comprueba invariantes de estado, alcance, evidencia y
solo lectura, sin imponer textos idénticos, hallazgos específicos ni exactamente dos
rondas al proveedor real. La prueba live usa `max_parallel=3`, separación de 1 segundo
entre arranques, 0,5 segundos entre solicitudes y backoff inicial de 5 segundos. Exige al menos un
investigador `completed`, con plan y evidencia, y una síntesis sin fallo pendiente.
Actividad de herramientas o planes sin evaluación completa ya no cuenta como éxito.
Se muestran también los diagnósticos saneados de investigadores y síntesis. Sin
activación explícita, esta prueba queda omitida, incluso con una API key.

## Límites conocidos

- La interpretación semántica de equivalencia, contradicciones y resolución sigue
  dependiendo del LLM. Las comprobaciones determinísticas validan identidad, estado,
  límites y referencias, no demuestran causalidad semántica ni exhaustividad.
- La detección determinística de contradicciones es conservadora (misma preocupación
  y criterio aceptados/rechazados); otras contradicciones dependen de la síntesis.
- Se usa contexto estructurado sin transcripciones ni repositorio completo, pero no
  se implementa compactación automática. Si excede el límite, la síntesis falla de
  forma explícita y la evaluación queda parcial.
  El límite predeterminado por llamada es 100.000 caracteres, tanto en el coordinador
  como en sus investigadores y ejecuciones independientes. Los runners derivan de él
  un presupuesto de entrada de 50.000 tokens estimados por llamada. Se mantienen los
  límites totales de tokens y el mínimo con el presupuesto del repositorio; aumentar
  contexto no elimina los posibles cortes por tokens ni la capacidad del proveedor.
- Reservas conservadoras y estimaciones de tokens pueden limitar una ejecución antes
  de agotar el uso real. Reintentos internos opacos del SDK no se contabilizan como
  llamadas separadas por el runtime existente. No se garantizan límites de facturación
  del proveedor; las reservas son guardas de ejecución y contabilidad del proyecto.
- No hay persistencia/cola durable ni reanudación tras cancelación; las invocaciones
  aparecen separadas en el informe y las trazas de esta ejecución.
- Pruebas offline ejercitan grafos/herramientas reales con transporte LLM simulado;
  no equivalen a una ejecución validada contra un proveedor real.
