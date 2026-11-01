import { useTranslation } from "react-i18next"

const labels = {
  en: {
    tab: "Incidents", date: "Date", dateNotRecorded: "Date not recorded",
    pageSize: "Incidents per page", pagination: "Incident pages",
    empty: "No incidents are recorded for this audit.", loadFailed: "Could not load audit incidents.",
    retry: "Retry", pending: "The audit is still active; new incidents may be recorded. Refresh to check for updates.",
  },
  es: {
    tab: "Incidentes", date: "Fecha", dateNotRecorded: "Fecha no registrada",
    pageSize: "Incidentes por página", pagination: "Páginas de incidentes",
    empty: "No hay incidentes registrados para esta auditoría.", loadFailed: "No se pudieron cargar los incidentes de la auditoría.",
    retry: "Reintentar", pending: "La auditoría sigue activa; pueden registrarse nuevos incidentes. Actualiza para consultar los cambios.",
  },
}

export function useAuditIncidentLabels() {
  const { i18n } = useTranslation("projects")
  return labels[i18n.resolvedLanguage?.startsWith("es") ? "es" : "en"]
}
