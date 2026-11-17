# TestIsolationAgent

Investigador de **Testabilidad** (maintainability v2). Pregunta canónica:

> ¿Los componentes pueden aislarse de sus dependencias para realizar pruebas
> independientes?

Responde con hallazgos (`TestIsolationFinding`) fundados en evidencia de
código (`EvidenceReference` con path + líneas + `content_hash`) y, cuando es
posible, con referencia documental (`document_claim_ids` de
`documented_architecture`, o la regla documental citada como evidencia fuente
en `ARCHITECTURE.md`/`docs/`). No audita arquitectura global, cohesión
funcional, cobertura de pruebas ni cumplimiento normativo; evalúa únicamente
las **barreras de sustitución/control** que impiden probar un componente en
aislamiento.

## Qué cuenta como barrera (y qué no)

Criterio fundamental: **una dependencia concreta, externa o global no es por
sí misma un defecto.** La decisión se toma por evidencia:

| Situación | Veredicto |
|---|---|
| La dependencia se instancia una vez en la raíz de composición (bootstrap/cli/main) y se inyecta | legítimo (configuración) |
| El componente recibe la dependencia por su constructor/parámetro tipado como puerto/protocolo/ABC, o existe factory | seam de sustitución; no barrera |
| El componente construye la dependencia él mismo sin seam (`self._x = Concreto(...)`) | barrera |
| Estado/dispositivo a nivel de módulo compartido entre instancias | barrera |
| Efectos no controlables (sleep/reloj real/red/fs/env/subprocess/Timer) sin inyección de reloj/sleeper/gateway/writer | barrera |
| Acceso a internos privados del adaptador (`x._connection...`) saltándose el puerto | barrera |
| Sin evidencia suficiente | inconclusive (con rangos faltantes) |

Monkeypatching **no** es un mecanismo de sustitución válido; solo seams
explícitos (constructor, factory, parámetro, registro con selección).

### Categorías de barrera usadas por el escáner determinista

`construction-coupling` · `construction-side-effect` · `global-state` ·
`shared-mutable-state` · `uncontrolled-time` · `async-control` ·
`subprocess-boundary` · `network-boundary` · `filesystem-boundary` ·
`configuration-boundary` · `adapter-internals`

`barrier_category` del candidato = categoría dominante de los hits en ese
archivo; el investigador sintetiza el mecanismo real a partir de la fuente.

## Arquitectura

Grafo cognitivo (idéntico a los v2 doc_driven):

```
START → plan_investigation (LLM) → investigate (LLM) ⇄ tools →
        ¿suficiente? → synthesis (determinista) → finalize (determinista) → END
```

- **plan_investigation** — el host construye un menú determinista
  (`planning.build_test_isolation_plan`), el LLM **solo rankea IDs** del menú
  y redacta preguntas (contrato `TestIsolationPlanSelection`; el host valida
  IDs y que cada pregunta nombre al componente). No hay findings en el menú.
- **investigate** — bucle LLM↔herramientas read-only
  (`TestIsolationInvestigation.investigate`). Reglas de proximidad, cobertura
  (`coverage_gap` no vacío impide `finding_candidate`/`no_finding`) y
  consistencia documental (`_validate_claims`). El LLM pide herramientas
  (`action=tools`) o cierra (`action=close`); recuperación de cobertura
  determinista si faltan rangos.
- **synthesis** — consolidación **lossless** por contenido de claim
  (`consolidate_candidates`, merge por JSON canónico, no por IDs locales) y
  evaluación documental local (`synthesize_documentary`; issues de integridad,
  nunca evaluación global; `global_compliance_established=False` siempre).
- **finalize** — emite `TestIsolationFinding` (provisional,
  `validation_status="insufficient_evidence"`) desde los candidatos
  consolidados; no hay revisión crítica (como los demás v2).

## Entrada y salida

```python
TestIsolationRequest(
    documented_architecture: ArchitectureContextResult | None,  # cacheada, determinista
    targets: list[str],        # opcional; limita el escaneo a rutas
    constraints: list[str],    # opcional; orientación para plan/investigate
    continuation: TestIsolationResult | None,
)
```

`TestIsolationResult`: `plan`, `findings`, `investigation_results`,
`candidates` (consolidados), `candidate_origins`, `documentary_synthesis`,
`evidence` (ledger), `termination_reason`.

Los candidatos llevan `document_claim_ids` (explícitos, `[]` permitido) e
`observed_mechanisms` + `substitution_blockers` (≥2 mecanismos y ≥1 bloqueante
para `finding_candidate`). Cada hallazgo indica `criterion_id="test-isolation"`.

## Cómo ejecutar

Desde `agent-server/` (PowerShell):

```powershell
# Contexto documental ya cacheado (no regenerarlo salvo necesidad)
uv run python src/test-agents/run_test_isolation_doc_driven.py `
  examples/harborcold-01/repository `
  --architecture-context examples/harborcold-01/architecture_context.json `
  --output-file artifacts/test-isolation-harborcold.json
```

Opciones: `--agent-config` (por defecto `dummy`), `--max-output-tokens`,
`--request`, `--config`, `--output json|readable`. Requiere `LLM_API_KEY`.

Evaluación contra el fixture (solo medición; los defects nunca son entrada):

```powershell
uv run python src/test-agents/evaluate_test_isolation.py `
  --result artifacts/test-isolation-harborcold.json `
  --defects examples/harborcold-01/harborcold-01-defects.json
```

Fixtures disponibles: `harborcold-01`, `lumenlib-01`, `stagecraft-01`
(8 casos confirmados + 3 controles negativos cada uno), `vetoria-01`
(**control negativo puro**: 0 casos esperados, 12 controles; el agente debe
producir 0 hallazgos) y `metropulse-01` (**repo sin oráculo** para corridas
ciegas de validación; no hay scoring, solo revisión manual).

Matching del evaluador (documentado en su docstring): componente + token de
mecanismo; controles negativos respetados si ningún hallazgo cae en ellos.

## Cómo continuar su desarrollo

1. **Léeme la bitácora**: `PROGRESS.md` (estado y corridas). Si lo continúas,
   actualízala en cada iteración.
2. Dónde vive la lógica delicada:
   - `planning.py` — escáner `_scan_source` (indicadores por categoría) +
     menú + bind documental (fase 1 explícito + afinidad de capacidad).
     Toda regla nueva debe ser pública y portable, nunca acoplada a fixtures.
   - `investigation.py` — bucle y `_validate_turn`/`_validate_claims`
     (contrato del LLM; mensajes de validación en `schemas.py`).
   - `execution.py` — `_repair_conclusion`: reparación mecánica aditiva antes
     del validador (ver sección siguiente).
   - `prompts/plan_investigation.md`, `prompts/investigate.md` — priors del
     LLM; cambiarlos suele ser el lever de mayor impacto en falsos positivos.
   - `synthesis.py`, `documentary.py` — consolidación lossless; tocar solo con
     tests equivalentes a los de los hermanos v2.
3. Reglas de aceptación del evaluador: por repo, **8/8 detectados con 0 falsos
   en controles negativos**. Si no se alcanza con el modelo configurado,
   documentar honestamente el techo (el fixture es orientativo; no sobreajustar
   prompts a un repo).
4. Invariantes del patrón que NO se deben romper: datos-solo como input,
   claims con provenance estricta, evidencia documental nunca en el ledger de
   código, `global_compliance_established=False`, determinismo de
   synthesis/finalize, read-only del toolset.

## Reparación mecánica de la conclusión (antes del validador)

El host aplica en `execution.py._repair_conclusion`, solo con ids que el
modelo ya produjo o entregados al modelo (nunca inventa):

- Unión en `conclusion.evidence_ids` de los ids entregados que las
  conclusiones citan en evaluaciones/candidatos.
- Unión en `candidate.evidence_ids` de las anclas de las claims contradicted
  que el candidato cita (o que el host le engancha).
- Enlace de claims contradicted sin candidato citante a candidato por
  solape máximo de evidencia (o primer candidato). Requisito del contrato
  `candidate_document_claim_mismatch` para `finding_candidate`.
- Poda de `symbol_ids`/`relationship_ids` fuera de los conjuntos
  visibles/examinados; filtrado de `document_claim_ids` a las del task.

La reparación NO cambia semántica: no crea claims, evaluaciones ni candidatos;
no convierte un `inconclusive` en `finding_candidate`; la validación
(`_validate_turn`/`_validate_claims`) se aplica íntegra tras reparar.

## Evidencia de generalización (2026-11-15)

> **Cobertura por tamaño de componente (desde 2026-11-15c):** el validador de
> cierre exige inspección completa solo en componentes **pequeños** (≤80
> líneas). En componentes **grandes** (p. ej. `app/sales/page.tsx`, 6.6k
> líneas) exige evidencia en las **líneas flaggeadas y las relaciones**, y
> reporta el alcance como limitación en lugar de bloquear el cierre. Es una
> corrección de diseño necesaria en repos reales: con el gate original,
> polleria cerraba inconclusive en ~13/16 investigaciones por "uninspected
> tail" de ficheros gigantes. El fixture pequeño conserva la garantía completa.

Verificado en la fase de iteración (ver PROGRESS.md):

- **Pista ciega sin oráculo** (`metropulse-01`, 81 ficheros): con el código
  final, el agente produjo **0 hallazgos: wiring legítimo, protocols y modelos
  de dominio son `no_finding` con justificación correcta** — sin ningún dato
  de la familia de fixtures en prompts ni lógica (grep exhaustivo; se encontró
  y se corrigió una referencia de ejemplo en un prompt).
- **Correcciones obtenidas por pruebas ciegas** (filtro de lenguaje para el
  escáner; cobertura inicial extendida) fueron bugs generales para cualquier
  repositorio, no parches de fixtures.
- **Control limpio externo** (`vetoria-01`): 0 hallazgos en la mayoría de
  corridas; las 12/12 controles negativos respetados en todas las corridas.
- Los conteos 24/24 + 21/21 se obtuvieron y mantienen en el código final;
  la temperatura 1.0 implica variabilidad entre corridas.
- **El repo ciego metropulse** distingue la frontera consumidor/costura en la
  mayoría de las corridas; los falsos residuales de "adapter frontera" muestran
  que esa distinción no está consolidada al 100% a temp 1.0.

Límites honestos que no desaparecen con las pruebas actuales:

- Los 4 fixtures y el repo ciego comparten familia de diseño (misma raíz de
  fixtures de evaluación); no hay validación sistemática sobre lenguajes ni
  código heredado fuera de esas familias. Desde 2026-11-15 el escáner y el
  grafo también cubren JS/TS (polleria: 949 ficheros, TS/TSX/Python), pero la
  verificación ahí es menos sistemática que en Python.
- La clase residual **adapter frontera** (adapter-candidato flaggeado como
  barrera en vez del consumidor) reaparece esporádicamente a temperatura 1.0;
  no produce falsos positivos en los controles, pero es un defecto de
  precisión conocido, no resuelto por el prompt.
- El corpus de evaluación fija el objetivo (8/8 + 0 FP en estos repos); no es
  una garantía de precisión universal.

## Limitaciones conocidas

- El preset `dummy` es temperature 1.0: resultados variables entre corridas.
- `architecture_context.json` está **partial** en los repos (3/4/6 claims en
  los fixtures; 13 en vetoria; 49 en metropulse); la vinculación documental
  phase-1 es débil por diseño del modelo extractor.
- El escáner es léxico y Python-solo: un componente puede no ser detectado si
  sus efectos viven tras una capa de indirección no nombrada; el investigador
  puede encontrarlos vía herramientas aunque el menú no lo haya flaggeado solo
  si el LLM selecciona ese candidato por afinidad documental.
- Sin revisión crítica: hallazgos son provisionales (`insufficient_evidence`).
- No evalúa cobertura de pruebas, métricas ni infraestructura externa real.
- **Cuota**: el preset `dummy` consume la cuota free-tier diaria de Gemini
  (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`) con amplificación
  AFC (hasta 10 llamadas remotas por `generateContent`). En el pasado la
  ventana diaria se agotó (HTTP 429); tras colocar una key nueva se trabaja en
  la misma cuota. Desactivar AFC en el wrapper, o un tier con billing,
  abarataría las iteraciones futuras.

## Próximos hitos naturales

- Cableado en coordinador/manager v2 (`maintainability_selection`).
- Entrada en catálogo/config (`AGENT_CONFIGS`) y `testability` como
  subcategoría pública.
- Tests de integración offline con LLM guionizado (ver
  `tests/test_maintainability_v2_integration.py` y los `tests_local/` de los
  hermanos).
- Documentar el agente en `docs/` si se registra.
