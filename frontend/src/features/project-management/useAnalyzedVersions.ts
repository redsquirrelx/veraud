import { useCallback, useState } from "react"
import { useTranslation } from "react-i18next"
import type { ParseKeys } from "i18next"
import { ApiError, listVersions, type VersionAnalysisSummary } from "../../infrastructure/http-client/httpClient.ts"
import { derivedStatusLabelKeys, statusLabelKey } from "./projectStatus.ts"

type AnalyzedVersionsFailure = { key: ParseKeys<"projects"> } | { detail: string }

function describeFailure(failure: unknown, key: ParseKeys<"projects">): AnalyzedVersionsFailure {
  return failure instanceof ApiError && failure.messageSource !== "client" ? { detail: failure.message } : { key }
}

/** Translation key for an analyzed-version status, or null when the backend
 *  sends a status without a known label (rendered verbatim). */
export function derivedStatusLabelKey(status: string): ParseKeys<"projects"> | null {
  return statusLabelKey(derivedStatusLabelKeys, status)
}

export function analyzedLabel(version: VersionAnalysisSummary, translateStatus?: (status: string) => string): string {
  const branch = version.branch ?? "?"
  const hash = version.commitHash?.slice(0, 7) ?? "?"
  const status = translateStatus === undefined ? version.derivedStatus : translateStatus(version.derivedStatus)
  return `${branch} @ ${hash} · ${status}`
}

export function useAnalyzedVersions(projectId: number | null) {
  const { t } = useTranslation("projects")
  const [tracked, setTracked] = useState<number | null>(projectId)
  const [versions, setVersions] = useState<VersionAnalysisSummary[]>([])
  const [loading, setLoading] = useState(false)
  const [failure, setFailure] = useState<AnalyzedVersionsFailure | null>(null)
  const error = failure === null ? "" : "detail" in failure ? failure.detail : t(failure.key)

  if (tracked !== projectId) {
    setTracked(projectId)
    setVersions([])
    setFailure(null)
  }

  const refresh = useCallback(async () => {
    if (projectId === null) {
      return
    }
    setLoading(true)
    setFailure(null)
    try {
      setVersions(await listVersions(projectId))
    } catch (failure) {
      setVersions([])
      setFailure(describeFailure(failure, "version.errors.loadAnalyzed"))
    } finally {
      setLoading(false)
    }
  }, [projectId])

  return { versions, loading, error, refresh }
}
