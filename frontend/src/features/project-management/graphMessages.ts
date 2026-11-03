export const graphMessages = {
  es: {
    queued: "Extracción en cola", preparing: "Preparando la versión seleccionada", extracting: "Extrayendo grafo con Graphify",
    saving: "Guardando grafo", completed: "Grafo generado", failed: "La extracción del grafo falló",
    startError: "No se pudo iniciar la extracción del grafo", loadError: "No se pudo consultar el estado del grafo",
    download: "Descargar grafo", independent: "Extracción estructural independiente, sin agentes auditores.",
    regenerate: "Regenerar grafo", retry: "Reintentar", success: "El grafo de {{commit}} se generó y guardó correctamente.",
    taskService: "Servicio", taskDetails: "Extracción del grafo estructural mediante Graphify.",
    showTaskDetails: "Mostrar detalles de {{name}}", hideTaskDetails: "Ocultar detalles de {{name}}",
    errors: {
      repository_unavailable: "No se encuentra el repositorio local. Sincroniza el proyecto antes de reintentar.",
      commit_unavailable: "El commit seleccionado no está disponible localmente. Sincroniza el proyecto y reintenta.",
      snapshot_failed: "No se pudo preparar una copia segura del commit seleccionado.",
      extractor_unavailable: "Graphify no está disponible en el agent-server. Revisa su instalación antes de reintentar.",
      timeout: "La extracción superó el tiempo límite. Puedes volver a intentarlo.",
      storage_failed: "No se pudo guardar el grafo. Revisa el espacio en disco y los permisos del agent-server.",
      extraction_failed: "Graphify no pudo completar la extracción. No se publicó ningún grafo incompleto.",
      interrupted: "La extracción se interrumpió por una cancelación o un reinicio. Puedes reintentar.",
      service_unavailable: "No se pudo contactar con el servicio de extracción. Comprueba que el agent-server esté disponible.",
      queue_full: "El servicio de extracción está ocupado. Espera unos momentos y reintenta.",
    },
  },
  en: {
    queued: "Extraction queued", preparing: "Preparing the selected revision", extracting: "Extracting graph with Graphify",
    saving: "Saving graph", completed: "Graph generated", failed: "Graph extraction failed",
    startError: "Could not start graph extraction", loadError: "Could not load graph status",
    download: "Download graph", independent: "Independent structural extraction, without audit agents.",
    regenerate: "Regenerate graph", retry: "Retry", success: "The graph for {{commit}} was generated and saved successfully.",
    taskService: "Service", taskDetails: "Structural graph extraction with Graphify.",
    showTaskDetails: "Show details for {{name}}", hideTaskDetails: "Hide details for {{name}}",
    errors: {
      repository_unavailable: "The local repository is unavailable. Sync the project before retrying.",
      commit_unavailable: "The selected commit is unavailable locally. Sync the project and retry.",
      snapshot_failed: "Could not prepare a safe snapshot of the selected commit.",
      extractor_unavailable: "Graphify is unavailable on the agent-server. Check its installation before retrying.",
      timeout: "Graph extraction exceeded its time limit. You can retry.",
      storage_failed: "Could not save the graph. Check disk space and agent-server permissions.",
      extraction_failed: "Graphify could not complete extraction. No incomplete graph was published.",
      interrupted: "Extraction was interrupted by cancellation or a restart. You can retry.",
      service_unavailable: "Could not reach the extraction service. Check that the agent-server is available.",
      queue_full: "The extraction service is busy. Wait a moment and retry.",
    },
  },
} as const

export function graphErrorMessageKey(error: string | null) {
  const code = error !== null && Object.hasOwn(graphMessages.en.errors, error)
    ? error as keyof typeof graphMessages.en.errors : "extraction_failed"
  return `errors.${code}` as const
}
