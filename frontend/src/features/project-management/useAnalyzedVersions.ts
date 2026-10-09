import { useCallback, useState } from "react"
import { ApiError, listVersions, type VersionAnalysisSummary } from "../../infrastructure/http-client/httpClient.ts"

function describeFailure(failure: unknown, fallback: string): string {
  if (failure instanceof ApiError) {
    return failure.message
  }
  return fallback
}

export function analyzedLabel(version: VersionAnalysisSummary): string {
  const branch = version.branch ?? "?"
  const hash = version.commitHash?.slice(0, 7) ?? "?"
  return `${branch} @ ${hash} · ${version.derivedStatus}`
}

export function useAnalyzedVersions(projectId: number | null) {
  const [tracked, setTracked] = useState<number | null>(projectId)
  const [versions, setVersions] = useState<VersionAnalysisSummary[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  if (tracked !== projectId) {
    setTracked(projectId)
    setVersions([])
    setError("")
  }

  const refresh = useCallback(async () => {
    if (projectId === null) {
      return
    }
    setLoading(true)
    setError("")
    try {
      setVersions(await listVersions(projectId))
    } catch (failure) {
      setVersions([])
      setError(describeFailure(failure, "Could not load analyzed versions"))
    } finally {
      setLoading(false)
    }
  }, [projectId])

  return { versions, loading, error, refresh }
}
