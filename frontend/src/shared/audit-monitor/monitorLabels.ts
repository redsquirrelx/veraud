import { useTranslation } from "react-i18next"

// Keep the new monitor-only copy here without changing locale JSON resources.
const labels = {
  en: {
    details: "Execution details", branch: "Execution and children", states: "Execution states", phases: "Graph phases", noPhase: "No active phase",
    execution: "Execution", dates: "Timeline", started: "Started", finished: "Finished", notRecorded: "Not recorded",
    tokens: "Token usage", error: "Execution error",
    resize: "Audit panel width", resizeHint: "Drag to resize, or use Left/Right arrows. Home: minimum; End: maximum.",
  },
  es: {
    details: "Detalles de ejecución", branch: "Ejecución e hijos", states: "Estados de ejecución", phases: "Fases del grafo", noPhase: "Sin fase activa",
    execution: "Ejecución", dates: "Fechas", started: "Inicio", finished: "Fin", notRecorded: "Sin registro",
    tokens: "Consumo de tokens", error: "Error de ejecución",
    resize: "Ancho del panel de auditorías", resizeHint: "Arrastra para ajustar o usa las flechas izquierda/derecha. Inicio: mínimo; Fin: máximo.",
  },
}

export function useMonitorLabels() {
  const { i18n } = useTranslation("projects")
  return labels[i18n.resolvedLanguage?.startsWith("es") ? "es" : "en"]
}

export const graphPhases = ["plan_investigation", "investigate", "evaluate_evidence", "review_findings", "finalize"] as const
