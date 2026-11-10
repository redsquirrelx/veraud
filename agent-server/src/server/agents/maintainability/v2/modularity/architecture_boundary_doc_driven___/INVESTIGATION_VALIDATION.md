# ShopLab: investigación documental (2026-11-07)

Este informe conserva la validación inicial de `investigate`. El runner fue ampliado
posteriormente hasta síntesis y finalización determinísticas; la consolidación de la
ejecución reciente completa está en [SYNTHESIS_VALIDATION.md](SYNTHESIS_VALIDATION.md).

## Alcance y reproducción

Proveedor/modelo: `gemini-3.5-flash-lite`. Mismo repositorio, contexto canónico,
commit `826448d3d445e5949f0cc6635f8799b3757459ee` y snapshot
`f2bcd83ecb003c94e53b0f7ae427dc42bbf9086c040eccbb6a85dff4d3e838a3`
que en la verificación de planificación. No se modificaron budgets ni mecanismos
de planificación. El runner ahora llega por defecto hasta investigación:

```powershell
uv run python -X utf8 src/test-agents/run_architecture_boundary_doc_driven.py "examples/shoplab/repository" --architecture-context "examples/shoplab/architecture_context.json" --output-file "investigation_doc_driven.json"
```

El resultado se sobrescribe si existe. `--plan-only` permite verificar solo el plan.

La primera ejecución real del runner tuvo 3 intentos de planificación, 88 692 tokens
contabilizados (68 036 estimados por fallos del proveedor); dejó solo 11 308 tokens
globales. `investigate` recuperó 4 evidencias iniciales pero no pudo admitir su
primera llamada con el margen restante: todas las tareas quedaron inconclusas,
con `token_limit`, sin falsear evaluación documental. Archivo:
`C:\Users\Duck\AppData\Local\Temp\opencode\shoplab-investigation-doc-driven.json`.

Para priorizar A/B/C sin repetir ese gasto se reutilizó el plan previamente guardado
`shoplab-planning-verified.json`, comprobando igualdad exacta de snapshot y commit.
Un harness externo ejecutó los métodos reales `investigate`/herramientas y validadores
en esas tres tareas, sin sintetizar ni confirmar findings. No es una segunda ejecución
completa de planificación: su contador de planificación es cero, y las métricas de
cobertura de selección originales se conservaron como históricas.

Harness: `C:\Users\Duck\AppData\Local\Temp\opencode\validate_shoplab_doc_investigation.py`.
Resultado real: `shoplab-investigation-abc.json` en ese mismo directorio.
Terminó `investigations_completed`: **4 intentos de modelo, 10 herramientas,
39 252 tokens contabilizados, incluidos 17 915 estimados por un 503**. Por tarea:
A 2 intentos/4 herramientas/25 175 tokens; B 1/3/7 589; C 1/3/6 488. La estimación
cargada por el 503 hace que A termine ligeramente sobre los 25 000 contabilizados
del límite local; no se alteró la contabilidad/retry heredada ni se amplió el budget.

## Referencias documentales

Todos los claims siguientes proceden de `docs/architecture/03-architecture-rules.md`.
Los IDs completos se conservan aquí para reconstruir los vínculos con el JSON:

| Alias | Claim ID | Línea | Obligación |
|---|---|---:|---|
| Ciclos | `document_claim_dc63b703a0166eadb533465c30a5718a82f2d88d68aaa22bb490aefae02841dc` | 45 | Orders, Inventory y Billing no deben formar ciclos estáticos o de runtime alcanzable. |
| Domain | `document_claim_60899ed9e076f5b7d8f3f3bfff36db2ad801a7e26d4c4174616c8d8d9f1eb341` | 9 | Domain no depende de Application, Infrastructure, Presentation o adaptadores concretos. |
| Estado privado | `document_claim_fbdcc0aff36fecde758c3ec6f68fb44ec8e4045766a24001315ef3203180b8a0` | 53 | Código externo no accede directamente al estado privado mutable de un adaptador. |
| Presentación | `document_claim_2e2e467d1f96e8cb81a9ae6d9771389e08407c18b93955e1454847dce46e5704` | 25 | Infrastructure no importa módulos o plantillas propiedad de Presentation. |

Estos IDs/secciones y sus citas **no** se insertaron en el ledger técnico.

## A: Orders ↔ Inventory

Tarea `investigation:c266f758f90a9cac5d85ad51`.
Asociado/evaluado: **Ciclos → contradicted**. Conclusión general:
`finding_candidate`; candidato local `candidate:cyclic-dependency-orders-inventory`.

Fuente entregada y citada:

| Evidencia técnica | Archivo / rango |
|---|---|
| `retrieval:0fcfa09e04f422ad0ba0584e` | `src/shoplab/orders/__init__.py:1–3` |
| `retrieval:863403d52859d46ecb080a06` | `src/shoplab/orders/service.py:1–10` |
| `retrieval:f3050a79615912428689b2b7` | `src/shoplab/inventory/allocator.py:1–8` |

El código entregado contiene un reexport en `orders/__init__.py`; los otros dos
archivos muestran además uso efectivo: `create_order()` llama `allocator.allocate()`
y `allocate()` llama `order_service.can_fulfill()`. La obligación incluye ciclos
estáticos, no solo ejecución dinámica. La respuesta fundó el candidato en esos
imports/usos, pero **no narró explícitamente la distinción del reexport ni registró
excepciones examinadas**. Solo la arista primaria del reexport fue devuelta por
`list_relationships`; las otras aristas planificadas no se aceptaron como IDs
examinados. El candidato no inventó IDs para ellas: citó fuente directamente.
No se ejecutaron funciones ni se probó alcance runtime. No se examinó Billing ni
las otras cinco porciones del claim global. Esta limitación semántica permanece.

## B: Domain → Infrastructure

Tarea `investigation:0431b7d464f36a63029ca4a0`.
Asociados/evaluados:

- **Domain → contradicted**.
- **Estado privado → not_applicable**: construir/invocar el notificador no equivale
  a alcanzar directamente su estado privado mutable.

Fuente: `retrieval:15bd3c7ae9ce2368966bcaf3` corresponde a
`src/shoplab/domain/checkout.py:1–7`; `retrieval:70c01f0e702c3ea8b4a95cc8`, a
`src/shoplab/infrastructure/console_notifier.py:3–7`.
Arista examinada: `relationship:924cb66c2e1c00cfedb646fb`.

`send_special_confirmation()` importa, construye `ConsoleNotifier()` y llama
`notifier.send()`: no es solo una importación sin uso. Resultado general
`finding_candidate`, candidato `candidate:domain_infrastructure_dependency`,
que conserva exclusivamente el claim contradicho como fundamento documental.
No se verificaron las otras porciones de independencia de Domain ni se registró
comprobación explícita de excepciones. La respuesta empleó el término convencional
"clean architecture" en impacto, aunque el fundamento observado fue la prohibición
documental concreta, no ese nombre de patrón. No se validó funcionalmente el envío.

## C: Infrastructure → Presentation

Tarea `investigation:4af62cc3634feffe8385a4c2`.
Asociado/evaluado: **Presentación → contradicted**.
Fuente: `retrieval:e9d4c1765c3ccb040a311ecd`,
`src/shoplab/infrastructure/receipt_delivery.py:1–7`; y
`retrieval:630866f85363bb40672028cb`,
`src/shoplab/presentation/email_templates.py:1–5`.
Arista examinada: `relationship:bcf96628ce53b497a06b136d`.

`LocalReceiptSender.send()` importa y llama `render_receipt()`, cuyo archivo declara
propiedad del canal de presentación. La confrontación se limitó a dependencia y
propiedad, sin juzgar el valor funcional del texto o el cálculo de importes.
Conclusión `finding_candidate`; candidato
`candidate:document_claim_2e2e467d1f96e8cb81a9ae6d9771389e08407c18b93955e1454847dce46e5704`.
No se examinó la segunda porción de la regla ni se registraron excepciones explícitas.

## Límites de esta validación

Verificación offline final: **203 tests pasaron, 2 omitidos; Ruff correcto**. Incluye
29 casos nuevos de la variante: ambos modos de investigación, resultados independientes,
integridad documental, citas inventadas/no examinadas, extremos de dependencias,
proyección acotada, cobertura local, reparación de evaluaciones, límites de herramientas,
runner hasta investigación y compatibilidad con síntesis/finalización. Los dos skips
son los casos exclusivamente documentales del test compartido de runners al
parametrizarlo sobre el runner original, que no se modificó.

- Tres candidatos **provisionales**, no tres findings confirmados. No hubo síntesis,
  revisión crítica ni aceptación. La confianza 1.0 que devolvió el modelo no cambia eso.
- Cuatro claims únicos examinados; los cuatro estados individuales fueron tres
  `contradicted` y uno `not_applicable`. La cobertura de planificación conserva
  `investigated=0`; la cobertura de investigación se informa separadamente.
- El modelo recibió solo los claims asociados, no otras posibles excepciones del
  catálogo general. Su ausencia no demuestra que no existan. El host final añade
  una advertencia por evaluación si `exceptions_examined=[]` y limita siempre el
  resultado al código citado; estas advertencias se añadieron después de la captura
  real, sin alterar los estados ni fabricar inspecciones.
- Validación de citas/procedencia no equivale a validación semántica total: no se
  comprueba por algoritmo que cada frase del modelo esté implicada por la fuente.
  Los tests offline comprueban contratos, recuperación, incertidumbre, separación de
  evidencias y reparación; no prueban comprensión semántica general del LLM.
- Se preservó el comportamiento del proveedor, sus retries y presupuestos. Un fallo
  de proveedor puede dejar tareas sin evaluar incluso cuando el código está disponible.
