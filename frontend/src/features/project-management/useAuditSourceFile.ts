import { useEffect, useState } from "react"
import { readAuditSourceFile, type AuditSourceFile } from "./qualityAuditApi.ts"

/** One revision-scoped file per mounted viewer. Evidence/symbol changes in the
 * same file do not start another read; obsolete requests cannot replace it. */
export function useAuditSourceFile(projectId: number | null, auditId: number | undefined, path: string | null, commit: string | null | undefined) {
  const [attempt, setAttempt] = useState(0)
  const key = `${projectId}-${auditId}-${commit}-${path}-${attempt}`
  const [stored, setStored] = useState<{ key: string, file: AuditSourceFile | null, failed: boolean } | null>(null)
  const enabled = projectId !== null && auditId !== undefined && path !== null && Boolean(commit)
  const current = stored?.key === key ? stored : null
  useEffect(() => {
    if (projectId === null || auditId === undefined || path === null || !commit) return
    const controller = new AbortController()
    queueMicrotask(() => {
      if (controller.signal.aborted) return
      readAuditSourceFile(projectId, auditId, path, controller.signal).then((file) => {
        if (controller.signal.aborted) return
        if (!file || file.path !== path || typeof file.commitHash !== "string" || file.commitHash.toLowerCase() !== commit.toLowerCase() || typeof file.content !== "string") {
          setStored({ key, file: null, failed: true })
        } else setStored({ key, file, failed: false })
      }, () => { if (!controller.signal.aborted) setStored({ key, file: null, failed: true }) })
    })
    return () => controller.abort()
  }, [projectId, auditId, path, commit, key])
  return { file: current?.file ?? null, loading: enabled && current === null, failed: current?.failed === true,
    retry: () => setAttempt((value) => value + 1) }
}
