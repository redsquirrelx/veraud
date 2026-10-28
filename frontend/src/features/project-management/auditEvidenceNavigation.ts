import { createContext } from "react"

/** The enclosing audit supplies the scope; finding/agent URL hints never own it. */
export const AuditEvidenceNavigation = createContext<string | null>(null)

export function auditEvidenceLink(basePath: string, evidenceId: string) {
  return `${basePath}?${new URLSearchParams({ tab: "evidence", evidence: evidenceId }).toString()}`
}
