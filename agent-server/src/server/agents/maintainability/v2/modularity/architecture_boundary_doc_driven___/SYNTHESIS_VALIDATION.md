# ShopLab: consolidación documental determinística

Validación del 2026-11-07, exclusivamente sobre el resultado reciente guardado en
`agent-server/plan_doc_driven.json`. Se invocó el nodo real `synthesis` sobre esos
datos: **sin llamadas LLM, herramientas ni nuevas inspecciones del repositorio**.
El archivo de entrada se conservó byte por byte. La ejecución original ya había
terminado las 12 investigaciones con presupuesto acumulado de tokens desactivado.

## Conteos antes y después

| Elemento | Antes | Después |
|---|---:|---:|
| Investigaciones originales | 12 | 12, sin modificar |
| Resultados `finding_candidate` | 4 | 4 originales preservados |
| Resultados `no_finding` | 8 | 8 originales preservados |
| Candidatos provisionales | 4 | 4 |
| Orígenes de candidatos | 4 implícitos en resultados | 4 explícitos en `candidate_origins` |
| Evaluaciones locales | 24 | 24, con IDs estables |
| Claims únicos evaluados | 19 | 19 |
| Evaluaciones `supported` | 18 | 18 locales |
| Evaluaciones `contradicted` | 4 | 4 locales |
| Evaluaciones `not_applicable` | 2 | 2 locales |
| Claims con alguna contradicción | 4 | 4 |
| Claims con alguna compatibilidad local | 16 | 16 |
| Claims con algún `not_applicable` local | 1 | 1 |
| Claims seleccionados sin evaluación efectiva | 0 | 0 |
| Claims con cobertura solo parcial | sin síntesis explícita | 19 |
| Inconsistencias de referencias detectadas | — | 0 |
| Nuevas llamadas/model tokens/herramientas | — | 0 / 0 / 0 |

Los conjuntos de claims por estado se superponen. No se suman 16+4+1 para calcular
claims únicos. No hay inconclusos en este resultado particular; los placeholders y
los inconclusos explícitos se comprueban mediante tests determinísticos.

Las evidencias, métricas previas de cobertura y consumo, catálogo documental y
conclusiones se compararon antes/después sin diferencias. Los cuatro candidatos
conservan exactamente sus campos, evidencia, severidad, claims documentales y
`confidence=1.0`; la síntesis no juzga ni aumenta esa confianza.

### Candidatos y orígenes

| Candidato | Investigación |
|---|---|
| `candidate:dc63b703a0166eadb533465c30a5718a` | `investigation:c266f758f90a9cac5d85ad51` |
| `candidate:checkout-console-notifier-import` | `investigation:7f987b1fe346e6280d47aa54` |
| `candidate:domain-infrastructure-dependency` | `investigation:0431b7d464f36a63029ca4a0` |
| `candidate:receipt_delivery_presentation_import` | `investigation:4af62cc3634feffe8385a4c2` |

Cada uno conserva dos referencias técnicas. Los IDs documentales no se insertaron
en `evidence_ids`. No fue necesario fusionar candidatos del caso real; la combinación
de evidencia, deduplicación exacta y colisiones se verificó separadamente en tests.

## Aciclicidad: dos observaciones, no una sobrescritura

Claim:
`document_claim_dc63b703a0166eadb533465c30a5718a82f2d88d68aaa22bb490aefae02841dc`.
La obligación y procedencia continúan en `plan.document_claims[claim_id]`:
`docs/architecture/03-architecture-rules.md`, línea 45, con índice y cita originales.

| Investigación | Estado original | Alcance original | Evidencia original |
|---|---|---|---|
| `documented_boundary:12542097769c1738b5c49c94` | `supported` | `src/shoplab/inventory/api.py` | `retrieval:20acde7a220c2ba03365bfb2` |
| `investigation:c266f758f90a9cac5d85ad51` | `contradicted` | `src/shoplab/orders/service.py`, `src/shoplab/inventory/allocator.py` | `retrieval:0cfb48cdc62b4a526ecad261`, `retrieval:70ece3260d8a659515a8e7e7` |

Ambas justificaciones, evidencias y limitaciones se mantienen por separado.
`has_contradiction=true` registra la contradicción localizada. La comparación usa
`scope_relation=different_scopes`; no califica las dos evaluaciones como conflicto
lógico. `coverage_status=partial` y `global_compliance_established=false` impiden
interpretar la compatibilidad de `inventory/api.py` como validación del grafo global.
La síntesis conserva el razonamiento previo, **no certifica su suficiencia semántica**
ni convierte la ausencia de ciclos observados en prueba adicional de conformidad.

## Otros claims con varias evaluaciones

| Claim | Evaluaciones |
|---|---|
| `document_claim_c0589fb58880de524917a791d8f9a5a40124648766045503ec966e41164083d0` — Infrastructure layer | Dos `supported`, en `console_notifier.py → domain/models.py` y `memory_quotes.py → application/contracts.py`. |
| `document_claim_e2b1febe3e114208faf4fb6db368a0904af38d2145a12acb4bd7b958756aa857` — Infrastructure allowed implementations and imports | Dos `supported` en esas mismas dos interacciones. No se fusionan los alcances. |
| `document_claim_fbdcc0aff36fecde758c3ec6f68fb44ec8e4045766a24001315ef3203180b8a0` — acceso a estado privado mutable de adaptadores | Dos `not_applicable` locales respecto al notificador y un `supported` respecto a `bootstrap.py`/`memory_catalog.py`. No se declara irrelevancia global. |

## Excepciones, entrega y otras limitaciones

- Las 24 evaluaciones conservan `exceptions_examined=[]` y sus advertencias: no se
  verificó que no existan excepciones. Ninguna excepción se infirió o reevaluó aquí.
- El JSON anterior no tenía recibos de entrega al prompt ni origen explícito de la
  evaluación. La síntesis conserva como efectivos los 24 registros que tienen
  evidencia fuente consistente, pero marca **entrega desconocida para los 19 claims**.
  Cero recibos registrados no significa cero claims entregados. No se fabricó ese dato.
- Las ejecuciones nuevas registran entrega y origen host. Un `host_pending` no cuenta
  como evaluación efectiva, aunque la investigación esté administrativamente cerrada.
- No existe una regla verificable de completitud global; por eso los 19 claims
  evaluados quedan con cobertura parcial, aun cuando todas sus tareas seleccionadas
  tengan una conclusión. Las porciones no seleccionadas siguen en el plan original.
- Igualdad de archivos no identifica una interacción exacta. Incluso con anclas
  técnicas iguales la síntesis solo señala una posible incompatibilidad para revisión;
  no resuelve diferencias de contexto o excepciones por similitud textual.
- No se hizo revisión crítica ni aceptación de findings. El runner ahora llega por
  defecto a `finalize`. En la versión histórica de esta validación se añadía
  `validation_status=insufficient_evidence` como adaptación al contrato anterior;
  el contrato documental V2 actual eliminó ese campo y `review_rationale`, sin
  cambiar las evaluaciones documentales originales aquí registradas.

## Artefactos y pruebas

En `C:\Users\Duck\AppData\Local\Temp\opencode\`:

- `validate_shoplab_documentary_synthesis.py`: reproducción offline del nodo real.
- `shoplab-documentary-synthesis.json`: resultado canónico con síntesis, sin sobrescribir
  el archivo original. Es replay de síntesis, no una nueva ejecución de investigación
  ni de finalización sobre ShopLab.

El recorrido completo del runner hasta finalización se verificó con herramientas
reales sobre fixtures y un modelo offline determinístico; no hubo llamadas al proveedor.

Verificación final: **236 tests pasaron, 2 omitidos; Ruff correcto**. Incluye 28 casos
nuevos de síntesis: estados locales, conflictos potenciales, intervalos de fuente,
placeholders, referencias inválidas, excepciones, serialización, determinismo,
deduplicación de candidatos y el runner hasta finalización. Los dos skips son las
variantes documentales del test compartido al parametrizarlo sobre el runner original.
