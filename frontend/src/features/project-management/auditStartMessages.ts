import { useTranslation } from "react-i18next"

const messages = {
  en: {
    revision: "Apply a branch and commit before starting an audit.",
    project: "The project is not ready to start an audit. Wait for synchronization or analysis to finish.",
    selection: "Select at least one available, configured agent in Configure audit. Unselected agents do not block execution.",
    requirements: "Provide between 1 and 100 functional requirements, each no longer than 10,000 characters.",
  },
  es: {
    revision: "Aplica una rama y un commit antes de iniciar una auditoría.",
    project: "El proyecto no está listo para iniciar una auditoría. Espera a que termine la sincronización o el análisis.",
    selection: "Selecciona al menos un agente disponible y configurado en Configurar auditoría. Los agentes no seleccionados no bloquean la ejecución.",
    requirements: "Introduce entre 1 y 100 requisitos funcionales, de hasta 10 000 caracteres cada uno.",
  },
}

export function useAuditStartMessages() {
  const { i18n } = useTranslation("projects")
  return messages[i18n.resolvedLanguage?.startsWith("es") ? "es" : "en"]
}
