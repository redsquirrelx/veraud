# Borrado de proyecto

`DELETE /api/projects/:id` elimina **de forma irreversible** un proyecto y todo
lo que le pertenece. El borrado es intencionalmente molesto de activar: desde
la UI ("Configuración del proyecto → Zona de peligro") exige escribir
`owner/repo` antes de confirmar.

## Semántica

1. **Guardas**: 404 si el proyecto no existe; 422 si hay tareas git
   (`Queued`/`Running`) en curso — no se pueden cancelar, así que se rechaza el
   borrado. Las ejecuciones de auditoría abiertas (`Waiting`/`Running`) sí son
   cancelables.
2. **Cancelación con espera**: para cada ejecución abierta del proyecto se
   solicita cancelación con el flujo existente (`cancelQualityAudit`, idéntico
   al botón "cancelar audit"). El servicio **espera** hasta que todas lleguen
   a un estado terminal (`Completed`/`Failed`) con un presupuesto de ~45 s.
   Si el agente no confirma a tiempo, **no se borra nada** y la respuesta es
   `202` con los IDs pendientes (`pendingExecutionIds`); reintentar la llamada
   con el agente terminando completa el borrado.
3. **Cascada de base de datos** (una transacción, ordenada por las FKs
   `RESTRICT`): `architecture_context_artifact` → `execution_event_stream`
   (y sus `execution_event`) → `agent_execution` → `evaluation` → `task`
   (y su `graph_extraction`) → `project.selected_version_id = null` →
   `project_version` → `project`. No se toca el schema ni se ejecuta ninguna
   migración.
4. **Disco (best effort)**: se elimina el clon (`<workspace>/<githubId>-<owner>-<repo>`)
   y las carpetas `.veraud-artifacts/<run_id>` cuyo `run_id` aparece en el JSON
   `result` de las ejecuciones del proyecto. Los fallos de disco se reportan
   en la respuesta (`disk.artifactFailures`, `disk.cloneFailure`) y **nunca**
   revierten el borrado de la base de datos; las carpetas no atribuibles no
   se tocan. `run_id` solo acepta `[a-zA-Z0-9-]{1,64}` para impedir path traversal.

## Lo que NO hace

- **No** reduce el archivo SQLite (la base local pesa ~3,2 GB): borrar filas no
  libera espacio sin `VACUUM`, que queda como operación manual con la
  aplicación cerrada.
- **No** borra `logs/` globales ni repositorios de GitHub.
- **No** elimina ejecuciones sin `evaluationId` atribuible al proyecto.
- **No** protege contra un agent-server que cree artefactos DESPUÉS de que se
  haya pedido su cancelación y llegado a terminal: las ejecuciones terminan y
  el agente deja de escribir, por lo que en la práctica no quedan residuos,
  aunque no se garantiza forense.

## Códigos de respuesta

| Código | Significado |
|---|---|
| 200 | Eliminado; respuesta con `counts` y `disk` (resumen de filas y archivos). |
| 202 | Ejecuciones abiertas pidieron cancelación; nada borrado aún. Reintentar. |
| 404 | El proyecto no existe. |
| 422 | Hay operaciones git en curso. Espera y reintenta. |
