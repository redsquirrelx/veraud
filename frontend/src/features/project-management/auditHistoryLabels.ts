import { useTranslation } from "react-i18next"

export function useAuditHistoryLabels() {
  const { i18n } = useTranslation("projects")
  return i18n.resolvedLanguage?.startsWith("es")
    ? { pageSize: "Auditorías por página", pagination: "Páginas del historial de auditorías" }
    : { pageSize: "Audits per page", pagination: "Audit history pages" }
}
