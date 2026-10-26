import { useCallback, useEffect, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import type { ParseKeys } from "i18next"
import { ApiError, readProjectFile, type ProjectFile } from "../../infrastructure/http-client/httpClient.ts"

type ProjectFileFailure = { key: ParseKeys<"projects"> } | { detail: string }

export function useProjectFile(projectId: number | null) {
  const { t } = useTranslation("projects")
  const [preview, setPreview] = useState<{ projectId: number, file: ProjectFile } | null>(null)
  const [loading, setLoading] = useState(false)
  const [failure, setFailure] = useState<ProjectFileFailure | null>(null)
  const error = failure === null ? "" : "detail" in failure ? failure.detail : t(failure.key)
  const mounted = useRef(true)
  const generation = useRef(0)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  const open = useCallback((path: string) => {
    if (projectId === null) {
      return
    }
    const owner = projectId
    generation.current += 1
    const token = generation.current
    const alive = () => mounted.current && generation.current === token
    setLoading(true)
    setFailure(null)

    void readProjectFile(owner, path).then(
      (result) => {
        if (!alive()) {
          return
        }
        setPreview({ projectId: owner, file: result })
        setLoading(false)
      },
      (failure: unknown) => {
        if (!alive()) {
          return
        }
        setPreview(null)
        setFailure(failure instanceof ApiError && failure.messageSource !== "client"
          ? { detail: failure.message } : { key: "detail.files.errors.readFailed" })
        setLoading(false)
      }
    )
  }, [projectId])

  // a preview always belongs to its project: switching projects hides it
  // without an effect, and leaving the page drops it with the unmount
  const file = preview !== null && preview.projectId === projectId ? preview.file : null

  const clear = useCallback(() => {
    generation.current += 1
    setPreview(null)
    setFailure(null)
    setLoading(false)
  }, [])

  return { file, loading, error, open, clear }
}
