# ResponsibilityAgent

Audita cohesión y distribución de responsabilidades, dentro de modularidad de
ISO/IEC 25010:2023. No es un coordinador ni realiza refactorizaciones.

## Ejecución con uv

Desde `agent-server`:

```powershell
uv run python src/test-agents/run_responsibility.py C:\repos\proyecto
uv run pytest src/test-agents/test_responsibility.py -q
uv run pytest src/test-agents -q
```

El ejecutor usa `config/dev-agents.yaml`, entrada `agents.dummy` por defecto.
`--agent-config NOMBRE` selecciona otra entrada existente. La clave es `LLM_API_KEY`
del `.env` de la raíz; la variable de entorno del mismo nombre tiene precedencia.
`--request archivo.json` configura contexto/criterios; `--config archivo.json`
configura límites/prompts. No se necesita cambiar YAML para ejecutar el agente.

El ejecutor comparte la configuración, snapshot, herramientas, presupuestos y
`LangSmithTracingBackend` con el anterior, pero instancia `ResponsibilityAgent` y
usa el span `responsibility`. `LANGSMITH_API_KEY` activa tracing; sin clave es no-op.
**Las trazas pueden enviar código/prompts al servicio**: para ocultarlos, configurar
`LANGSMITH_HIDE_INPUTS=true` y `LANGSMITH_HIDE_OUTPUTS=true` en `.env`.
Las pruebas usan modelos simulados y fixtures: no requieren claves ni consumen API.

## Diseño y reutilización

El grafo compartido está en `runtimes/investigation/`: planificación, ReAct con
`ToolNode`, evaluación, enrutamiento determinístico, revisión interna y finalización.
Se extrajo del agente de límites sin cambiar su flujo, defaults, validaciones ni
prompts; los imports públicos previos se mantienen compatibles. No hay un framework
nuevo ni orquestación superior. Cada auditor puede ejecutarse independientemente.

```python
agent = ResponsibilityAgent(chat_model, ResponsibilityConfig(max_iterations=3))
result = await agent.run(fresh_repository_toolset, ResponsibilityRequest())
```

Las mismas siete herramientas existentes permiten consultar archivos, símbolos,
relaciones, fragmentos, referencias textuales, evidencias e infraestructura sobre un
snapshot de solo lectura. `find_symbols(file_path=...)` y los fragmentos permiten
examinar métodos/atributos; no hay una herramienta nueva de métricas o llamadas.
Las relaciones estáticas no se interpretan automáticamente como llamadas runtime.
La política existente excluye `README`/documentación narrativa: proporcionar sus
criterios como contexto declarado y conservar esa limitación en la salida.

## Especialización y resultados

Los prompts investigan propósito común, comportamientos, clientes, estado compartido,
motivos de cambio independientes, ubicación, justificaciones y contraevidencia.
Los contratos específicos agregan `component_assessments`, responsabilidades,
comportamientos, motivos de cambio, conflictos y citas favorables/contrarias.

La finalización del host resuelve IDs reales de archivos/símbolos, exige código propio
inspeccionado para atribuir responsabilidades, verifica citas/commit y no permite
aceptar candidatos basados solo en métricas o nombres. Los conflictos deben explicar
responsabilidades distintas, sus motivos de cambio y un riesgo de mantenimiento.
Esto valida trazabilidad y requisitos mínimos, no demuestra semánticamente la
independencia de responsabilidades: interpretación y revisión siguen siendo del LLM.

`components_investigated` incluye responsabilidades y evidencias normalizadas, con
estado de validación. `findings` conserva aceptados, rechazados e insuficientes: filtrar
`validation_status == "accepted"` para reportar problemas confirmados. Se conservan
hipótesis descartadas, investigaciones inconclusas, limitaciones y consumo disponible.
Una ruta exacta de archivo puede normalizarse a su ID canónico; los directorios y
alias ambiguos no se resuelven por inferencia. Las evaluaciones sin identidad válida
se conservan en `unresolved_component_assessments` con cohesión inconclusa y trabajo
pendiente en `missing_information`.

`critical_review` conserva la revisión especializada. Cada hipótesis confirmada o
descartada requiere un juicio independiente sobre su alcance, citas comprobadas y
evaluaciones de componentes válidas; sin ese respaldo queda inconclusa. Esto también
se aplica cuando no hay candidatos. Una revisión bloqueada se registra como trabajo
pendiente, conservando las observaciones locales como interpretaciones no verificadas.
`source_backed` verifica soporte mínimo de código y procedencia de una evaluación;
no certifica cohesión global ni ausencia de ciclos en implementaciones no inspeccionadas.
Las conclusiones sin criterio explícito son observaciones de diseño, no incumplimientos.
Una clase grande/coordinadora puede ser coherente; no hay cuotas ni umbrales de SRP.

Los límites de llamadas, herramientas, iteraciones, contexto, tiempo y tokens son los
compartidos. También se conserva la detención conservadora por `context_limit`:
esta extracción no introduce compactación ni altera el comportamiento del auditor anterior.
