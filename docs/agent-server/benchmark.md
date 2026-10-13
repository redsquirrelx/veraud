# Benchmark de analyzer → architect → judge

El benchmark ejecuta los agentes actuales sobre seis repositorios reales de
`appdata/workspace`. No modifica los checkouts ni las instrucciones de los agentes.
La suite está en `agent-server/benchmarks/workspace.yaml`.

## Ejecutar

Desde `agent-server`, validar primero los commits y todas las referencias:

```bash
uv run benchmark validate
```

Ejecutar una primera pasada de los seis casos:

```bash
uv run benchmark run --repeats 1
```

Para medir estabilidad, el valor por defecto es tres repeticiones:

```bash
uv run benchmark run
```

Una prueba pequeña o una comparación con otro modelo:

```bash
uv run benchmark run --case pyshop --repeats 1
uv run benchmark run --case pyshop --case mario --provider groq --model openai/gpt-oss-120b --repeats 3
```

También funciona `uv run --no-sync python -m server.run_benchmark ...`, incluso
si todavía no se ha reinstalado el entrypoint `benchmark`.

Se usan `config/dev-agents.yaml` y `LLM_API_KEY` como en los runners existentes.
`validate` y `report` no llaman al LLM. `run` sí consume la API del proveedor.
Las ejecuciones son secuenciales para limitar interferencia y carga simultánea.

### Ritmo y límites del proveedor

Por defecto hay una pausa mínima de **12 segundos después de cada intento de
llamada**, compartida por analyzer, architect, ambos jueces, casos y repeticiones.
Esto limita el benchmark a como máximo unos cinco intentos del adaptador por
minuto, sin contar reintentos internos del SDK. Los SDK pueden aplicar su propia
política de reintentos dentro de un intento observado por el benchmark.

Los errores transitorios (HTTP 408, 429, 500, 502, 503, 504 y fallos de conexión)
permiten hasta tres reintentos adicionales. Las esperas crecen de 30 a 60 y 120
segundos, respetando esperas mayores indicadas mediante `Retry-After` o el
`RetryInfo` estructurado de Gemini. Si se agotan los reintentos, la siguiente
llamada también respeta el enfriamiento; no se reinicia el ritmo al pasar de
etapa o repositorio. Errores de autenticación o configuración no se reintentan.

Para un proveedor con cuotas más bajas:

```bash
uv run benchmark run --request-interval 20 --max-retries 3 --retry-backoff 60 --timeout 1200 --judge-timeout 600
```

Las pausas consumen el timeout de cada etapa/pipeline. La consola imprime código
HTTP y espera cuando hay un reintento. El informe separa tiempo de espera,
reintentos y eventos HTTP 429; una llamada recuperada no se cuenta como fallida.
Los artifacts guardan cada intento sin incluir mensajes privados del proveedor.
Una cuota diaria agotada requiere que se renueve la cuota: las pausas no la
aumentan. Los clientes del proveedor se cierran al finalizar o interrumpir un caso.

## Casos y referencia independiente

| Caso | Proyecto | Aspecto evaluado |
|---|---|---|
| `pyshop` | Django PyShop | Modelos, vistas y routing de una aplicación pequeña |
| `hexagonal-python` | Hexagonal architecture Python | Puertos, adaptadores y servicios FastAPI |
| `mario` | MarioPygame | Aplicación de escritorio y bucle de juego |
| `gitfolio` | Next.js GitFolio | Página/layout de framework y exportación estática |
| `hexagonal-typescript` | Domain Driven Hexagon | NestJS, módulos y adaptadores SQL |
| `fastapi` | FastAPI | Biblioteca grande con abundante documentación/tests |

Los commits están fijados. Antes de llamar al modelo, se comprueban checkout
limpio, existencia de archivos y rangos de líneas. Se registra un hash del
contenido de los archivos admitidos por RepoMap y se verifica de nuevo al acabar
cada ejecución. Si cambia el código, hay que revisar la referencia y actualizar
la suite; el benchmark no cambia automáticamente los commits esperados.

Las referencias se construyeron inspeccionando fuentes, no preguntando a otro
LLM. Son una primera anotación revisable, no una verdad exhaustiva de cada
repositorio. Las listas de componentes son mínimos relevantes: se informa
**recall contra la referencia**, y no se penaliza como incorrecto todo componente
adicional. La precisión solo se calcula si la referencia declara ser exhaustiva.

GitFolio es un sitio estático y el vocabulario actual no contiene `web_app` ni
`static_site`. Su clasificación no se puntúa; sí se evalúan lenguaje, puntos de
entrada y componentes. No se fuerza una etiqueta incorrecta para conseguir una
exactitud artificial.

## Qué se mide

### Automáticamente

- Exactitud de tipo de proyecto y lenguaje. Una ejecución sin salida cuenta como
  fallo de estas métricas cuando existe etiqueta de referencia.
- Recall de puntos de entrada y componentes relevantes.
- Fracción de componentes con responsabilidad escrita. Es completitud, no
  corrección semántica.
- Validez de citas: archivo dentro del repositorio y rangos dentro del archivo.
  Esto no prueba que la cita respalde la afirmación.
- Duración por etapa, llamadas LLM, tiempo de llamadas, caracteres de prompts,
  errores de proveedor, JSON inválido y cancelaciones.
- Uso observado de tokens y costo, cuando la respuesta del proveedor lo permite.
- Estabilidad entre pares de repeticiones: tipo, estilo, componentes y conjuntos
  de evidencia de notas. Las ejecuciones fallidas/degradadas no generan una
  falsa apariencia de estabilidad.
- Estadísticas/límites de recolección y visibilidad de las referencias. Así se
  detecta si FastAPI queda parcialmente fuera de los primeros 500 archivos.

Los límites actuales se mantienen: el architect recolecta con sus valores
internos de 500 archivos, profundidad 8 y 8 archivos por ronda, aunque se cambien
`--max-files`, `--max-depth` o `--files-per-round`. Los límites efectivos quedan
registrados en cada etapa.

### Evaluación independiente del juez

Cada caso incluye tres afirmaciones etiquetadas: respaldada, contradicha y no
verificable, con evidencia y justificación. El juez recibe solo afirmación y
código; las etiquetas esperadas no entran en sus prompts. Son 18 juicios por
pasada completa, además de los juicios sobre el informe generado.

Se calcula matriz de confusión, exactitud, precisión/recall/F1 por clase,
macro-F1 y tasa de aceptación de afirmaciones falsas. Los juicios ausentes por
error/timeout se muestran en la cobertura; no se convierten en aciertos.
Las afirmaciones no verificables iniciales se centran en rendimiento de
producción que no puede inferirse del código. Es un conjunto de calibración
pequeño y sencillo; una buena puntuación no prueba dominio de afirmaciones
arquitectónicas ambiguas. Se puede ampliar editando `judge_claims`.

El judge del flujo y el judge de calibración usan el mismo modelo subyacente que
el architect. Sus llamadas y costos se registran por separado. La calibración
evalúa al juez; los veredictos sobre el informe son un diagnóstico de
autoevaluación, no una referencia independiente de la calidad del architect.

### Revisión humana de calidad

Para cada ejecución se genera `reviews/<caso>-<repeticion>.json` con:

- Afirmaciones del resumen, estilo, intención, flujo de datos, responsabilidades,
  notas, desviaciones, contenedores y riesgos.
- Hechos relevantes de referencia que el informe debería reconocer.

Completar `reviewer`, `verdict` (`supported`, `contradicted` o `unverifiable`),
`found` (`true`/`false`) y comentarios. Los campos no revisados permanecen
`null`; no cuentan como errores ni como aciertos. No cambiar las afirmaciones,
los ids o el hash. El reporte rechaza revisiones asociadas a otro resultado.

```bash
uv run benchmark report results/benchmark/<ejecucion>
```

Se informan tasas de respaldo/contradicción/no verificabilidad, recall de hechos
relevantes y completitud de revisión. Los porcentajes de revisión parcial solo
representan los ítems revisados. Una entrada puede contener varias proposiciones;
para una evaluación estricta, el revisor debe comprobarlas todas y documentar
afirmaciones mixtas en el comentario. Recomendable comparar dos revisores en
una muestra antes de usar las cifras como criterio de aceptación.

## Resultados y reproducibilidad

Cada ejecución crea un directorio nuevo bajo `agent-server/results/benchmark/`:

```text
environment.json  # versiones, hashes de código/suite, opciones sin API key
suite.json        # copia de la referencia
runs/*.json       # resultados completos, tiempos, llamadas y métricas
reviews/*.json    # plantilla de anotación humana
summary.json      # resumen y métricas por ejecución
report.md         # informe legible
```

No se sobrescriben directorios existentes. Cada caso terminado se guarda antes
de seguir, con su informe actualizado. El timeout del pipeline es compartido
por analyzer y architect; judge y calibración tienen cada uno su propio
`--judge-timeout`. `pipeline_seconds` excluye jueces; `total_seconds` incluye
ambos. El informe distingue etapas completadas, degradadas, fallidas, expiradas
y omitidas. Los fallbacks o errores de modelo no se cuentan simplemente como
éxitos útiles porque la función haya devuelto JSON.

La consola muestra cada etapa en su propia línea. Si termina como `degraded`,
indica todas las causas detectadas: clasificación `unknown`, falta de
responsabilidades, llamadas fallidas o respuestas JSON inválidas. Por ejemplo:

```text
  pipeline=completed; tiempo total=190.1s
    analyzer=completed
    architect=degraded (2 respuestas JSON inválidas)
    judge=completed
    judge_calibration=completed
```

Estas causas también quedan guardadas en
`stages.<etapa>.degradation_reasons` del JSON de la ejecución.

Los artifacts no incluyen credenciales ni texto completo de prompts: registran
hash y tamaño del prompt. Los resultados y citas sí describen el repositorio.
El tracing LangSmith conserva su configuración habitual.

### Costo

Opcionalmente indicar tarifas **USD por millón de tokens**:

```bash
uv run benchmark run --provider groq --model openai/gpt-oss-120b --input-price 0.15 --output-price 0.60
```

Los valores son un ejemplo de cálculo, no una tarifa verificada. Usar las tarifas
vigentes del modelo/proveedor elegido. La pareja de tarifas se aplica a todas
las etapas: si la configuración usa modelos distintos, realizar ejecuciones
con un override común o dejar costo sin puntuar.

El costo solo se calcula si todas las llamadas tienen consumo observado y hay
tarifas. Un error, una cancelación o metadatos ausentes dejan el costo en `null`;
los tokens parciales siguen visibles. Gemini devuelve actualmente solo texto,
por lo que su adaptador no expone tokens al benchmark. No se estiman tokens a
partir de caracteres ni se interpreta consumo desconocido como cero.

## Comparar cambios

Ejecutar baseline y variante con la misma suite, commits, presupuestos y número
de repeticiones, en directorios distintos. Comparar calidad humana y recall,
calibración del juez, errores, tiempos y costo conjuntamente. Tres repeticiones
permiten observar variación, no sostener conclusiones estadísticas fuertes.
Los hashes de código y configuración resuelta por etapa permiten identificar
qué cambió.
