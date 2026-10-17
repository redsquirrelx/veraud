# AuditReportAgent

Agente de ensamblado documental que construye un informe JSON de calidad a partir
**exclusivamente del Blackboard**, limitado a un `run_id`. No lee el repositorio,
no vuelve a ejecutar los investigadores y no realiza llamadas a modelos.

## Contrato y convenciones

- `agent.py`: ciclo público sin estado y topología LangGraph
  `read_blackboard → assemble_report → validate_traceability`.
- `execution.py`: organización documental, estadísticas, riesgos y trazabilidad.
- `knowledge.py`: interpretación de contratos existentes y categorías de auditoría.
- `schemas.py`: exportaciones públicas; contratos canónicos en `agents/schemes/report.py`.
- No existe configuración vacía ni parámetros de proveedor: esta ejecución es
  determinista. Por ello no participa en el catálogo de configuraciones LLM.
- Solo consulta la interfaz `Blackboard`; no depende de su repositorio de almacenamiento.

```python
from server.agents.audit_report import AuditReportAgent, AuditReportRequest

report = await AuditReportAgent(blackboard=blackboard).run(
    AuditReportRequest(run_id=run_id),
)
document = report.model_dump_json(indent=2)
schema = report.model_json_schema()
```

El llamador decide dónde persistir `document`. El agente no modifica registros del
blackboard. Cada ejecución lee una vista nueva y emite fecha de informe y digest
SHA-256 de los registros de origen. El blackboard actual no ofrece lectura
transaccional global; una auditoría en curso puede producir un informe parcial.

## Diez secciones del documento (`schema_version: "1.0"`)

| Sección | Campo JSON |
| --- | --- |
| 1. Portada e identificación | `identification` |
| 2. Resumen ejecutivo | `executive_summary` |
| 3. Objetivos y alcance | `objectives_and_scope` |
| 4. Metodología y criterios | `methodology_and_criteria` |
| 5. Descripción del software | `software_description` |
| 6. Resultados y hallazgos | `quality_results` |
| 7. Análisis de riesgos | `consolidated_risks` |
| 8. Conclusiones generales | `general_conclusions` |
| 9. Recomendaciones y mejora | `recommendations_and_improvement_plan` |
| 10. Anexos y trazabilidad | `annexes_and_traceability` |

Las secciones están tipadas para su posterior transformación en un documento
formal. Las afirmaciones procedentes de agentes conservan su texto original y
referencias; no se inventa una traducción ni una interpretación técnica nueva.

El agente genera el resumen ejecutivo en español a partir de alcance, conteos por
estado, resultados verificados e incidencias de ejecución. No se limita a copiar la
síntesis del supervisor. La generación es determinista, sin llamadas LLM: no añade
juicios técnicos nuevos ni convierte errores de ejecución en defectos del software.
Las limitaciones del cuerpo principal se sintetizan; los textos originales quedan
en anexos y registros de ejecución.

## Resultados y referencias

`quality_results.attributes` admite atributos y subcaracterísticas abiertos. Incluye
Mantenibilidad, Seguridad y Adecuación funcional; los dos últimos son `not_evaluated`
mientras no existan resultados publicados. Mantenibilidad incluye modularidad,
reusabilidad, analizabilidad, modificabilidad y capacidad de prueba, cada una con
su estado, temas, síntesis, hallazgos y conclusión. Las dimensiones no implementadas
permanecen `not_evaluated`, aunque se haya completado el alcance solicitado.

Los agentes de mantenibilidad actuales se mapean por identidad. Nuevos agentes
pueden declarar `quality_attribute` y `subcharacteristic` en `Finding.details`, y
usar `Assessment.quality_attribute` / `Assessment.details.subcharacteristic`, sin
modificar el esquema ni los otros atributos. No se deduce la categoría de un título.

Cada hallazgo mantiene su ID global de blackboard y su criterio, severidad, impacto,
recomendación, componentes y evidencias. Los estados son `verified`, `inconclusive`
y `discarded`. Una aceptación requiere soporte técnico resoluble en esta auditoría
y atribución consistente de revisión; los conflictos, referencias ausentes y
commits no verificados no se convierten en defectos confirmados. La evidencia
snapshot-only conserva esa condición, sin atribuirse a un commit.

Los grupos consolidados conservan sus IDs y se resuelven usando
`invocation_id/local_id`, nunca IDs locales de otra ejecución. Los retiros se marcan
descartados y los grupos disputados inconclusos. Los conteos indican explícitamente
`counting_basis: "blackboard_finding_records"`: cuentan contribuciones originales,
sin deduplicar por similitud de títulos. `consolidation_ids` permite reconocer los
grupos registrados. Las fortalezas explícitas, como abstracciones útiles, no se
presentan como riesgos. No se suman consumos de padres e hijos (se solapan).

Los riesgos y acciones correctivas se basan solo en hallazgos verificados. La
prioridad deriva de severidad publicada; el criterio de corrección se identifica
como **propuesto**, no como una prueba que ya se ejecutó. La ausencia de hallazgos
no se presenta como cumplimiento de ISO ni como garantía global de calidad.

Los anexos preservan archivo, líneas, símbolos, hash, snapshot, commit, verificación
Git, productor, ejecución y llamada de herramienta. También mantienen métricas,
diagramas y grafos cuando existen; no crean artefactos que no fueron publicados.
Campos desconocidos (por ejemplo descripción comercial o URL remota) quedan
vacíos/nulos. No se infiere arquitectura a partir de carpetas ni se inventan pruebas
dinámicas a partir de la mera existencia de tests.

## Integración y descarga

Las auditorías iniciadas por `AuditService` publican el inventario técnico y el
estado terminal como metadatos del Blackboard. Los investigadores publican nombres
y mediciones de herramientas junto a sus referencias. Así el informe no necesita
consultar el servicio de ejecución ni el filesystem para obtener esos datos.

```http
GET /api/audits/{run_id}/report
```

Devuelve JSON (`Cache-Control: no-store`) y admite vistas parciales durante la ejecución.
Para guardarlo en PowerShell:

```powershell
Invoke-WebRequest "http://localhost:8000/api/audits/$runId/report" -OutFile informe.json
```

La representación Word se descarga mediante `GET /api/audits/{run_id}/report.docx`:

```powershell
Invoke-WebRequest "http://localhost:8000/api/audits/$runId/report.docx" -OutFile informe.docx
```

El conversor `services/audit_report_docx.py` presenta las diez secciones con estilos,
tablas y referencias, sin llamadas LLM ni cambios en los resultados. La conversión
se ejecuta fuera del event loop y no utiliza archivos temporales. Para el mismo JSON,
produce bytes idénticos: fija metadatos y fechas internas del contenedor DOCX. Dos
peticiones pueden tener distinta fecha de emisión, porque cada una obtiene un nuevo
JSON del agente; la garantía de reproducibilidad corresponde al mismo documento JSON.

Objetos y listas se presentan como tablas Word y viñetas, también en los campos
anidados, métricas y referencias. Los inventarios de tecnologías, dependencias y
entorno tienen tablas específicas y los encabezados de tabla se repiten por página.
No se serializan objetos JSON dentro de celdas. El informe incluye un diagnóstico
por agente, con incidencias técnicas y registros de origen en los anexos.

Las tablas usan ancho fijo dentro del área útil de una página A4, celdas alineadas
arriba y contenido anidado aplanado en párrafos; no se crean tablas dentro de celdas.
Hallazgos y evidencias tienen referencias breves (`Hallazgo H001`, `Evidencia E001`)
con hipervínculos a marcadores internos de sus secciones. También se enlazan riesgos,
acciones, evaluaciones y ejecuciones. El ID completo permanece en la información
emergente del enlace y en el JSON canónico; el contenido literal de las evidencias
no se reescribe. Los marcadores son estables para el mismo JSON.

`annexes_and_traceability.execution_issues` y el campo `execution_issues` del snapshot
HTTP proceden del mismo intérprete (`services/audit_diagnostics.py`). Se incluyen
invocaciones fallidas sin evidencias propias mediante el resultado conservado por
su supervisor. Las causas heredadas no se repiten como si fueran errores propios
de cada nivel. En el blackboard se muestra un resumen con detalles desplegables.

También se puede reconstruir offline desde una exportación de
`GET /api/audits/{run_id}`:

```powershell
uv run python src/test-agents/run_audit_report.py blackboard.json --output informe.json
```

Este comando restaura los registros en un Blackboard en memoria y ejecuta el mismo
agente; no usa credenciales ni llama al proveedor. La instancia en memoria del servidor
solo conserva auditorías durante la vida del proceso.

## Verificación

```powershell
uv run pytest tests/test_audit_report.py tests/test_audits.py tests/test_blackboard_publication.py -q
uv run ruff check src/server/agents/audit_report src/server/agents/schemes/report.py
```
