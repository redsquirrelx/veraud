import { useCallback, useEffect, useRef, useState } from "react"
import { getQualityAuditConfiguration, type AuditConfigurationHistory } from "./qualityAuditApi.ts"

/** Keep the selection cached between tabs; refresh receipts while this tab is
 * visible and the audit is running. Never overlap configuration requests. */
export function useAuditEvidenceAgents(projectId: number, auditId: number, active: boolean, pending: boolean, revision: number) {
  const [attempt, setAttempt] = useState(0)
  const key = `${projectId}-${auditId}-${revision}`
  const [stored, setStored] = useState<{ key: string, value?: AuditConfigurationHistory, failed: boolean } | null>(null)
  const current = stored?.key === key ? stored : null
  const retry = useCallback(() => setAttempt((value) => value + 1), [])
  const completed = useRef<string | null>(null)
  useEffect(() => {
    const requestKey = `${key}-${attempt}`
    if (!active || (!pending && completed.current === requestKey)) return
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    async function load() {
      try {
        const value = await getQualityAuditConfiguration(projectId, auditId, controller.signal)
        if (controller.signal.aborted) return
        if (!pending) completed.current = requestKey
        setStored({ key, value, failed: false })
      } catch {
        if (controller.signal.aborted) return
        setStored((previous) => ({ key, value: previous?.key === key ? previous.value : undefined, failed: true }))
      }
      if (pending && !controller.signal.aborted) timer = setTimeout(() => void load(), 5000)
    }
    void load()
    return () => { controller.abort(); clearTimeout(timer) }
  }, [projectId, auditId, active, pending, key, attempt])
  return { history: current?.value, failed: current?.failed === true, retry }
}
