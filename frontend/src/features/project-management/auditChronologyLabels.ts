import { useTranslation } from "react-i18next"

const labels = {
  en: {
    tab: "Chronology", demoNote: "DEMO: agent executions, ordered by start time. No real audit data or additional requests.",
    order: "Parent → child → descendant, ordered by execution start. Executions without a recorded start appear last.",
    empty: "No executions are recorded for this audit.", agent: "Execution path",
  },
  es: {
    tab: "Cronología", demoNote: "DEMO: ejecuciones de agentes ordenadas por inicio. Sin datos reales ni peticiones adicionales.",
    order: "Padre → hijo → descendiente, en orden de inicio de ejecución. Las ejecuciones sin inicio registrado aparecen al final.",
    empty: "No hay ejecuciones registradas para esta auditoría.", agent: "Ruta de ejecución",
  },
}

export function useAuditChronologyLabels() {
  const { i18n } = useTranslation("projects")
  return labels[i18n.resolvedLanguage?.startsWith("es") ? "es" : "en"]
}
