import { useCallback, useEffect, useState } from "react"
import { getQualityAuditReportSection } from "./qualityAuditApi.ts"
import type { AuditReportSection } from "./qualityAuditReport.ts"

type SectionState = { status: "loading" } | { status: "loaded", data: unknown } | { status: "error" }

export function useAuditReportSection(projectId: number, auditId: number, section: AuditReportSection, enabled: boolean, revision = 0) {
  const key = `${projectId}-${auditId}-${section}-${revision}`
  const [stored, setStored] = useState<{ key: string, state: SectionState } | null>(null)
  const state: SectionState = stored?.key === key ? stored.state : { status: "loading" }
  const retry = useCallback(() => setStored({ key, state: { status: "loading" } }), [key])

  useEffect(() => {
    if (!enabled || state.status !== "loading") return
    const controller = new AbortController()
    getQualityAuditReportSection(projectId, auditId, section, controller.signal).then((result) => {
      if (!controller.signal.aborted) setStored({ key, state: { status: "loaded", data: result.data } })
    }, () => {
      if (!controller.signal.aborted) setStored({ key, state: { status: "error" } })
    })
    return () => controller.abort()
  }, [projectId, auditId, section, key, enabled, state.status])

  return { state, retry }
}

export type AuditReportSectionResource = ReturnType<typeof useAuditReportSection>
