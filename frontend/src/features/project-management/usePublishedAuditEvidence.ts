import { useCallback, useEffect, useState } from "react"
import { getPublishedAuditEvidence, type PublishedAuditEvidence } from "./qualityAuditApi.ts"

/** Poll only the open active-audit view. Requests never overlap, and failures
 * retain the last successful records rather than making evidence disappear. */
export function usePublishedAuditEvidence(projectId: number, auditId: number, enabled: boolean) {
  const key = `${projectId}-${auditId}`
  const [stored, setStored] = useState<{ key: string, value?: PublishedAuditEvidence, failed: boolean } | null>(null)
  const [attempt, setAttempt] = useState(0)
  const retry = useCallback(() => setAttempt((value) => value + 1), [])
  const current = stored?.key === key ? stored : null

  useEffect(() => {
    if (!enabled) return
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    async function load() {
      let again = true
      try {
        const value = await getPublishedAuditEvidence(projectId, auditId, controller.signal)
        if (controller.signal.aborted) return
        setStored({ key, value, failed: false })
        again = value.partial
      } catch {
        if (controller.signal.aborted) return
        setStored((previous) => ({ key, value: previous?.key === key ? previous.value : undefined, failed: true }))
      }
      if (again && !controller.signal.aborted) timer = setTimeout(() => void load(), 5000)
    }
    void load()
    return () => { controller.abort(); clearTimeout(timer) }
  }, [projectId, auditId, enabled, key, attempt])

  return { state: current?.value ? { status: "loaded" as const, data: current.value.data }
    : current?.failed ? { status: "error" as const } : { status: "loading" as const },
  value: current?.value, failed: current?.failed === true, retry }
}
