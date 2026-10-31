import { useTranslation } from "react-i18next"
import { stateLabelKey, type AuditRunState } from "./auditStatus.ts"

// Keep the new monitor-only copy here without changing locale JSON resources.
const labels = {
  en: {
    actions: "Audit actions", cancel: "Cancel", cancelAudit: "Cancel audit", cancelTitle: "Cancel audit?",
    cancelWarning: "Cancelling this audit will stop its pending tasks.",
    cancelTarget: "Selected audit", cancelConsequences: "What happens if you cancel?",
    cancelUnavailable: "Preview only: confirming will close this dialog without stopping the audit.",
    cancelling: "Cancelling…", cancelled: "Cancelled", cancelRequested: "Cancellation requested. Waiting for the server to confirm that execution has stopped.",
    cancelError: "Could not confirm the cancellation request. You can retry.", retryCancel: "Retry cancellation", dismiss: "Close",
    keepRunning: "Keep running", confirmCancel: "Confirm cancellation",
    details: "Execution details", branch: "Execution and children", states: "Execution states", phases: "Graph phases", noPhase: "No active phase",
    execution: "Execution", dates: "Timeline", started: "Started", finished: "Finished", notRecorded: "Not recorded",
    tokens: "Token usage", error: "Execution error", viewError: "View error",
    affectedComponent: "Affected component or agent", incidentDate: "Incident date", errorType: "Error type",
    recordedMessage: "Recorded message", errorNotRecorded: "Not recorded", errorContext: "Viewed from",
    descendantError: "An execution in this branch has an error",
    resize: "Audit panel width", resizeHint: "Drag to resize, or use Left/Right arrows. Home: minimum; End: maximum.",
  },
  es: {
    actions: "Acciones de la auditoría", cancel: "Cancelar", cancelAudit: "Cancelar auditoría", cancelTitle: "¿Cancelar auditoría?",
    cancelWarning: "Al cancelar esta auditoría se detendrán sus tareas pendientes.",
    cancelTarget: "Auditoría seleccionada", cancelConsequences: "¿Qué ocurre al cancelar?",
    cancelUnavailable: "Vista previa: confirmar cerrará este cuadro sin detener la auditoría.",
    cancelling: "Cancelando…", cancelled: "Cancelada", cancelRequested: "Cancelación solicitada. Esperando a que el servidor confirme la detención.",
    cancelError: "No se pudo confirmar la solicitud de cancelación. Puedes reintentar.", retryCancel: "Reintentar cancelación", dismiss: "Cerrar",
    keepRunning: "Seguir ejecutando", confirmCancel: "Confirmar cancelación",
    details: "Detalles de ejecución", branch: "Ejecución e hijos", states: "Estados de ejecución", phases: "Fases del grafo", noPhase: "Sin fase activa",
    execution: "Ejecución", dates: "Fechas", started: "Inicio", finished: "Fin", notRecorded: "Sin registro",
    tokens: "Consumo de tokens", error: "Error de ejecución", viewError: "Ver error",
    affectedComponent: "Componente o agente afectado", incidentDate: "Fecha del incidente", errorType: "Tipo de error",
    recordedMessage: "Mensaje registrado", errorNotRecorded: "No registrado", errorContext: "Consultado desde",
    descendantError: "Una ejecución de esta rama presenta un error",
    resize: "Ancho del panel de auditorías", resizeHint: "Arrastra para ajustar o usa las flechas izquierda/derecha. Inicio: mínimo; Fin: máximo.",
  },
}

export function useMonitorLabels() {
  const { i18n } = useTranslation("projects")
  return labels[i18n.resolvedLanguage?.startsWith("es") ? "es" : "en"]
}

export function useAuditStateLabel() {
  const { t } = useTranslation("projects")
  const labels = useMonitorLabels()
  return (state: AuditRunState) => state === "cancelling" ? labels.cancelling
    : state === "cancelled" ? labels.cancelled : t(stateLabelKey(state))
}

export const graphPhases = ["plan_investigation", "investigate", "evaluate_evidence", "review_findings", "finalize"] as const
