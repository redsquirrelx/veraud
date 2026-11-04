import { useCallback, useEffect, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import type { ParseKeys } from "i18next"
import { ApiError, listProjectFiles } from "../../infrastructure/http-client/httpClient.ts"
import { treeFromPaths, type DirectoryTreeNode } from "../../shared/ui-kit/index.ts"

interface LoadedTree {
  key: string
  tree: DirectoryTreeNode
}

type ProjectTreeFailure = { key: ParseKeys<"projects"> } | { detail: string }

export function useProjectTree(projectId: number | null, rootName: string) {
  const { t } = useTranslation("projects")
  const [loaded, setLoaded] = useState<LoadedTree | null>(null)
  const [loading, setLoading] = useState(false)
  const [failure, setFailure] = useState<ProjectTreeFailure | null>(null)
  const error = failure === null ? "" : "detail" in failure ? failure.detail : t(failure.key)
  const mounted = useRef(true)

  const key = projectId === null || rootName === "" ? null : `${projectId}:${rootName}`

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  const refresh = useCallback(() => {
    if (projectId === null || rootName === "") {
      return
    }
    const next = `${projectId}:${rootName}`
    setLoading(true)
    setFailure(null)

    void listProjectFiles(projectId).then(
      (result) => {
        if (!mounted.current) {
          return
        }
        setLoaded({ key: next, tree: treeFromPaths(rootName, Array.isArray(result.files) ? result.files : []) })
        setLoading(false)
      },
      (failure: unknown) => {
        if (!mounted.current) {
          return
        }
        setLoaded(null)
        setFailure(failure instanceof ApiError && failure.messageSource !== "client"
          ? { detail: failure.message } : { key: "detail.files.errors.loadFailed" })
        setLoading(false)
      }
    )
  }, [projectId, rootName])

  // the tree of another project is never shown, and leaving the page drops it
  const tree = loaded !== null && loaded.key === key ? loaded.tree : null

  return { tree, loading, error, refresh }
}
