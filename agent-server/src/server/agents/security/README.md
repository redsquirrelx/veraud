# Seguridad en el flujo de auditoría

El pipeline `quality-audit` acepta `attributes: ["security"]` y una configuración
de modelo/credencial con la clave `security`. También acepta
`attributes: ["maintainability", "security"]`: una única ejecución comparte
instantánea, `run_id`, Blackboard y presupuesto global de tokens y produce un solo
análisis exportable y un informe JSON/Word con ambos atributos. Cada análisis tiene
su propia identidad de invocación y sus límites de ejecución. Un fallo de uno deja
su recibo explícito y conserva los resultados del otro; la cancelación detiene ambos.
`["maintainability"]` conserva la jerarquía existente. El frontend permite elegir
el atributo y configurar su acceso al modelo en **Configuración → Auditoría**.

La API directa `POST /api/audits` admite la misma lista `attributes`. Para ambos:

```json
{
  "repository_path": "C:/workspace/repositorio",
  "attributes": ["maintainability", "security"],
  "request": {"objective": "Evaluar mantenibilidad", "targets": []},
  "security_request": {"objective": "Evaluar seguridad", "targets": []}
}
```

Se puede proporcionar un `config` de modelo común o `agent_configs` con los nueve
IDs de mantenibilidad y `security` con su propia selección. El backend prepara
ambas selecciones antes de crear la única ejecución; la lista seleccionada se
conserva también durante el seguimiento previo al informe.

Por compatibilidad, omitir `attributes` y enviar `security_request: {}` selecciona
solo seguridad. Admite objetivo y rutas objetivo en ese contrato. El
pipeline admite el mismo contrato mediante `security_request`.

`audit.py` adapta los componentes de `SecuritySupervisorAgent`: SAST, secretos,
dependencias, enriquecimiento, propuestas de remediación, validador de parches y
filtro legacy. Los escáneres leen copias temporales de los fragmentos autorizados
por el toolset de la instantánea; no modifican el checkout. Los límites de lectura
y archivos dejan cobertura parcial explícita. `SecurityAuditConfig`, en
`config.py`, compone los controles comunes de ejecución y añade `max_scan_files`.
`SecurityConfig` conserva la política del módulo legacy.

## Configuración operativa

La API directa, el input del pipeline `quality-audit` y
`POST /api/projects/{projectId}/audits` aceptan las mismas opciones operativas:

- `agent_defaults`: contexto, tokens personales, llamadas al modelo y llamadas a
  herramientas. En seguridad se aplican directamente. En mantenibilidad se conserva
  la semántica de la jerarquía: los límites comunes de llamadas se aplican a los
  investigadores y `call_limits` ajusta los presupuestos agregados.
- `security_config`: campos específicos que sobrescriben los comunes solo para
  seguridad. Los campos omitidos conservan los valores resueltos. Las cuotas
  `provider_rate_limits` también se combinan por campo, incluido `null` para
  desactivar una cuota concreta. Requiere seleccionar `security`.
- `audit_budget.max_total_tokens`: presupuesto global compartido, independiente del
  límite local `max_total_tokens` de seguridad. Se respetan ambos; aumentar uno no
  aumenta el otro. Su omisión conserva el presupuesto global predeterminado del
  servidor, independientemente de `agent_defaults` y `security_config`.
- `call_limits`: exclusivo de la jerarquía de mantenibilidad. Para seguridad se
  utilizan `agent_defaults` o `security_config`.

Por ejemplo, este body ya es válido para la API directa:

```json
{
  "repository_path": "C:/workspace/repositorio",
  "agent_config": "dummy",
  "attributes": ["security"],
  "agent_defaults": {
    "max_context_characters": 20000000,
    "max_total_tokens": 80000000,
    "max_model_calls": 20,
    "max_tool_calls": 30
  },
  "audit_budget": {"max_total_tokens": 3000000000},
  "security_config": {
    "max_scan_files": 30,
    "max_source_lines": 200
  }
}
```

`security_config` deriva su esquema y restricciones de `SecurityAuditConfig`, y
la configuración completa se revalida con el catálogo antes de aceptar la tarea.
Incluye los cuatro límites comunes, `max_output_tokens`, `max_scan_files`,
`max_source_lines`, `max_source_characters`, duración, cuotas y política de
reintentos del proveedor. Las opciones sin consumidor en seguridad, prompts y
credenciales no se aceptan como controles. Los paneles de usuario continúan usando
`describe_agent_config`/`validate_agent_config` con nivel `user`; estas opciones de
auditoría de bajo nivel se identifican como configuración de desarrollador.

Los límites de contexto del modelo, archivos, herramientas y fragmentos de código
son independientes. El toolset también conserva sus límites de respuesta y de
recuperación acumulada; una lectura que no cabe queda documentada como pendiente.
El timeout de `config` acota la ejecución completa; un timeout específico menor en
`security_config` puede acortar seguridad. En ejecución conjunta, cada atributo
conserva su propio límite y ambos están acotados por el plazo global.

`Assessment.details.security_analysis.effective_config` conserva los valores
resueltos y `audit_token_limit` conserva el presupuesto global, sin credenciales.
Estos datos viajan con el análisis exportado y con la trazabilidad documental.

Las propuestas usan el modelo seleccionado, pacing/reintentos acotados, cuotas y
el presupuesto compartido; los fallos conservan el parche local. Los intentos sin
consumo comunicado retienen su reserva estimada. La cancelación conserva evidencia,
el candidato en curso y un recibo terminal de consumo.

Blackboard conserva reglas, severidad, OWASP, CWE, remediación, resultado del filtro
y el campo `verified` legacy en `details.security_finding`. Ese campo no equivale
a validación técnica: los candidatos se publican como `insufficient_evidence`,
incluidos los descartados por el filtro, cuyo resultado queda identificado en
`legacy_filter_kept`. Las credenciales detectadas se redactan en fragmentos y
campos enviados al modelo/publicados; los hashes siguen identificando el contenido
original de la instantánea.

La ejecución queda `completed` cuando termina todas las lecturas y etapas previstas,
con motivo `security_scope_completed`. Queda `partial` si hay alcance vacío, límites
de archivos/lecturas, errores de lectura, fragmentos truncados o propuestas del modelo
sin completar, con sus motivos específicos en `security_analysis.incomplete_reasons`.
La cancelación conserva el motivo `security_interrupted`.

El alcance heurístico se conserva como limitación independiente del estado de
ejecución: SCA compara nombres sin resolver versiones y DAST no se ejecuta. Completar
la ejecución no verifica los candidatos ni certifica seguridad. JSON y Word documentan
estas limitaciones. El análisis se exporta e importa con los mismos endpoints/CLI del
flujo existente; el generador documental no necesita acceso al repositorio ni al
proveedor para reconstruir el informe de diez secciones.
