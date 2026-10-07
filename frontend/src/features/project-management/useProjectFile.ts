import { useCallback, useEffect, useRef, useState } from "react"
import { ApiError, readProjectFile, type ProjectFile } from "../../infrastructure/http-client/httpClient.ts"

export function useProjectFile(projectId: number | null) {
  const [preview, setPreview] = useState<{ projectId: number, file: ProjectFile } | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
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
    setError("")

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
        setError(failure instanceof ApiError ? failure.message : "Could not read the file")
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
    setError("")
    setLoading(false)
  }, [])

  return { file, loading, error, open, clear }
}
