# TestControllabilityAgent — investigador documental

Investigador documental de **Testabilidad** (maintainability v2). Responde a:

> ¿Los componentes permiten controlar las entradas, estados, dependencias y
> condiciones necesarios para probar sus comportamientos documentados?

Es el hermano documental de `test_isolation_doc_driven`: reutiliza su
infraestructura cognitiva (grafo `START → plan_investigation → investigate ⇄
tools → synthesis → finalize → END`), la entrega documental sin confianza,
la consolidación sintética sin evaluaciones y la reparación mecánica de
conclusiones. Lo que cambia es el dominio: **controlabilidad** (establecer y
variar condiciones de una prueba), no sustitución de colaboradores en sentido
estricto.

## Pregunta y alcance

Identificar obstáculos de controlabilidad que dificulten pruebas reproducibles,
aisladas y deterministas de los comportamientos **documentados** de un
componente:

- **Entradas y estado:** ¿se puede establecer el estado inicial del componente
  (p. ej. depósitos, colecciones, procesos ya abiertos)?
- **Tiempo y aleatoriedad:** ¿se pueden fijar instantes de referencia y fuentes
  no deterministas para comportamientos gobernados por plazos, ventanas o IDs?
- **Errores:** ¿se pueden provocar y reproducir los escenarios de fallo
  documentados (rechazo de terminal, host inaccesible, firma inválida,
  timeout)?
- **Concurrencia:** ¿se puede controlar cuándo se ejecutan y cuándo terminan
  los trabajos diferidos/concurrentes?
- **Configuración:** ¿se pueden fijar opciones que rigen el comportamiento sin
  depender del entorno ambientado del proceso?

No es hallazgo: una dependencia directa o la ausencia de mocks por sí solas.
Todo hallazgo debe demostrar una dificultad concreta para controlar un
escenario de prueba relevante y documentado.

## Estructura

Idéntica a `test_isolation_doc_driven`:

| Módulo | Papel |
| --- | --- |
| `agent.py` | `TestControllabilityAgent(InvestigationAgent)`; `agent_type="test_controllability"`. |
| `config.py` | `TestControllabilityConfig` (máx. 16 investigaciones, 6 claims por candidato). |
| `planning.py` | Plan determinista por código fuente; indicadores exploratorios; afinidad documental; menú acotado. |
| `investigation.py` | Bucle tools/LLM, validación, cobertura (gate small/large). |
| `execution.py` | Grafo + reparación mecánica de conclusiones. |
| `schemas.py` | Contratos canónicos (`TestControllabilityRequest`, escenario `finding_candidate`/`no_finding`/`inconclusive`). |
| `state.py` / `documentary.py` / `synthesis.py` | Estado, entrega documental sin confianza, consolidación sin evaluación nueva. |
| `prompts/` | Criterio legítimo vs costura de control vs barrera; hallazgos de controlabilidad. |
| `tests_local/` | Checks locales del escáner determinista. |

## Indicadores deterministas (exploratorios, nunca hallazgos)

`_scan_source` (Python y JS/TS vía `language` del snapshot, nunca por nombre de
archivo): `subprocess-boundary`, `network-boundary`, `nondeterminism`
(`secrets.*`, `random.*`, `uuid4/1`, `Math.random`, `crypto.randomUUID`…),
`uncontrolled-time` (incluido `date.today()`), `async-control` (Timer/Thread/
setInterval…), `configuration-boundary` (env en cualquier línea; la
clasificación import-time la decide el investigador), `filesystem-boundary`,
`adapter-internals`, `construction-side-effect`, además de
`construction-coupling`, `global-state`, `shared-mutable-state` (incl.
`_booked_slots = set()` a nivel de módulo y nombres declarados en carpetas de
dominio excluidos como "constructores benignos"). El comentario de un indicador
nunca basta; la validación del agente exige ≥2 mecanismos de barrera distintos.

## Reparación mecánica de la conclusión

Igual que en aislamiento: unión aditiva de IDs entregados, linkado de claims
`contradicted` a candidatos por solape de evidencia, poda a visibles, jamás
invención de IDs ni `inconclusive`→finding. La semántica la conserva el modelo;
la integridad mecánica, el host.

## Ejecución (PowerShell desde `agent-server/`)

```powershell
uv run python src/test-agents/run_test_controllability_doc_driven.py examples/testcontrollability/civitaspermit-01/repository --architecture-context examples/testcontrollability/civitaspermit-01/architecture_context.json --output-file artifacts/test-controllability-civitaspermit.json
```

El `architecture_context.json` de cada fixture está **en caché** en su carpeta
(fuera de `repository/`); regenerarlo requiere un repositorio git y
`run_architecture_context.py --agent-config architecture_context` (resultado
`partial` por limitación de extracción del modelo; el agente tolera contexto
parcial). Los fixtures `*-defects.json` son **solo oráculo del evaluador**,
nunca entrada del agente.

## Evaluación

```powershell
uv run python src/test-agents/evaluate_test_controllability.py --result artifacts/test-controllability-civitaspermit-001.json --defects examples/testcontrollability/civitaspermit-01/civitaspermit-01-defects.json
```

Regla de dos ejes (componente × mecanismo) airtight para controles negativos;
un hallazgo detecta un caso si ambos ejes coinciden en el mismo registro. Envuelve
`result.findings` + `result.candidates`.

## Invariantes que no deben romperse

- Input de datos puro (sin objetivo externo como instrucción).
- Claims documentales nunca entran al ledger de evidencia técnica.
- `global_compliance_established=False` siempre; síntesis y finalize sin
  llamadas a modelo.
- Toolset de solo lectura; presupuestos, pacing y cuotas compartidos sin cambios.
- Reglas de escáner/validación **generalizadas**: ningún id, ruta o nombre de
  fixture en prompts, reglas o puntajes.

## Estado

Ver [PROGRESS.md](PROGRESS.md). Cableado en V2 (coordinator registry + catalog).
