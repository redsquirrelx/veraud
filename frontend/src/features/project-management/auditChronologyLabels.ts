import { useTranslation } from "react-i18next"

const labels = {
  en: {
    tab: "Chronology", event: "Event", date: "Occurred at", retry: "Retry", refresh: "Refresh events", timeout: "Timed out", rejected: "Rejected",
    order: "Global chronological order. Consecutive events from the same execution path form a time interval; any intervening path starts a new block. Expand each block to see exact event times. History may be incomplete; older audits are not backfilled.",
    pageSize: "Blocks per page", events: "events", sort: "Chronological order", oldest: "Oldest first", newest: "Newest first",
    moreEvents: "Show next 20 events",
    empty: "No events are recorded for this audit.", agent: "Execution path",
    loadFailed: "Could not load the chronology.", pagination: "Execution path pages", pending: "Execution in progress. Chronology updates automatically every 3 seconds.",
    updateFailed: "Could not update the chronology. Showing the last loaded events; you can retry with Refresh events.",
  },
  es: {
    tab: "Cronología", event: "Evento", date: "Fecha del evento", retry: "Reintentar", refresh: "Actualizar eventos", timeout: "Tiempo agotado", rejected: "Rechazado",
    order: "Orden cronológico global. Los eventos consecutivos de una misma ruta forman un intervalo; si aparece otra ruta, comienza un nuevo bloque. Despliega cada bloque para ver las fechas exactas. El historial puede estar incompleto; las auditorías anteriores no se reconstruyen.",
    pageSize: "Bloques por página", events: "eventos", sort: "Orden cronológico", oldest: "Más antiguos primero", newest: "Más recientes primero",
    moreEvents: "Mostrar siguientes 20 eventos",
    empty: "No hay eventos registrados para esta auditoría.", agent: "Ruta de ejecución",
    loadFailed: "No se pudo cargar la cronología.", pagination: "Páginas de rutas de ejecución", pending: "Ejecución en curso. La cronología se actualiza automáticamente cada 3 segundos.",
    updateFailed: "No se pudo actualizar la cronología. Se muestran los últimos eventos cargados; puedes reintentar con Actualizar eventos.",
  },
}

export function useAuditChronologyLabels() {
  const { i18n } = useTranslation("projects")
  return labels[i18n.resolvedLanguage?.startsWith("es") ? "es" : "en"]
}
