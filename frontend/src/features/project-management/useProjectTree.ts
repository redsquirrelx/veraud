import { useCallback, useEffect, useRef, useState } from "react"
import { ApiError, listProjectFiles } from "../../infrastructure/http-client/httpClient.ts"
import { treeFromPaths, type DirectoryTreeNode } from "../../shared/ui-kit/index.ts"

interface LoadedTree {
  key: string
  tree: DirectoryTreeNode
}

export function useProjectTree(projectId: number | null, rootName: string) {
  const [loaded, setLoaded] = useState<LoadedTree | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")
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
    setError("")

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
        setError(failure instanceof ApiError ? failure.message : "Could not load the project files")
        setLoading(false)
      }
    )
  }, [projectId, rootName])

  // the tree of another project is never shown, and leaving the page drops it
  const tree = loaded !== null && loaded.key === key ? loaded.tree : null

  return { tree, loading, error, refresh }
}
