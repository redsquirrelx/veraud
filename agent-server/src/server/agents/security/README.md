# Seguridad en el flujo de auditoría

El pipeline `quality-audit` acepta `attributes: ["security"]` y una configuración
de modelo/credencial con la clave `security`. Cada ejecución selecciona un atributo;
`["maintainability"]` conserva la jerarquía existente. El frontend permite elegir
el atributo y configurar su acceso al modelo en **Configuración → Auditoría**.

La API directa `POST /api/audits` selecciona seguridad mediante
`security_request: {}`. Admite objetivo y rutas objetivo en ese contrato. El
pipeline admite el mismo contrato mediante `security_request`.

`audit.py` adapta los componentes de `SecuritySupervisorAgent`: SAST, secretos,
dependencias, enriquecimiento, propuestas de remediación, validador de parches y
filtro legacy. Los escáneres leen copias temporales de los fragmentos autorizados
por el toolset de la instantánea; no modifican el checkout. Los límites de lectura
y archivos dejan cobertura parcial explícita. `SecurityAuditConfig`, en
`config.py`, compone los controles comunes de ejecución y añade `max_scan_files`.
`SecurityConfig` conserva la política del módulo legacy.

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

El resultado es parcial por el alcance heurístico del módulo: SCA compara nombres
sin resolver versiones y DAST no se ejecuta. JSON y Word documentan estas
limitaciones. El análisis se exporta e importa con los mismos endpoints/CLI del
flujo existente; el generador documental no necesita acceso al repositorio ni al
proveedor para reconstruir el informe de diez secciones.
