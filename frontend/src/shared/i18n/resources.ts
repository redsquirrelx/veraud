import enCommon from "./locales/en/common.json"
import enProjects from "./locales/en/projects.json"
import enSettings from "./locales/en/settings.json"
import enAgents from "./locales/en/agents.json"
import enTasks from "./locales/en/tasks.json"
import esCommon from "./locales/es/common.json"
import esProjects from "./locales/es/projects.json"
import esSettings from "./locales/es/settings.json"
import esAgents from "./locales/es/agents.json"
import esTasks from "./locales/es/tasks.json"
import { auditEvidenceMessages } from "../audit-monitor/auditEvidenceMessages.ts"

export const defaultNS = "common"
export const fallbackLanguage = "en"
export const supportedLanguages = ["es", "en"] as const
export type SupportedLanguage = typeof supportedLanguages[number]

export const resources = {
  en: {
    auditEvidence: auditEvidenceMessages.en,
    common: enCommon,
    projects: enProjects,
    settings: enSettings,
    agents: enAgents,
    tasks: enTasks,
  },
  es: {
    auditEvidence: auditEvidenceMessages.es,
    common: esCommon,
    projects: esProjects,
    settings: esSettings,
    agents: esAgents,
    tasks: esTasks,
  },
} as const
