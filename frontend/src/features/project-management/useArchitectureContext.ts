import { useEffect, useState } from "react"
import { getArchitectureContextContent, type ArchitectureContextContent } from "./architectureContextApi.ts"

type ArchitectureContextState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; context: ArchitectureContextContent | null }

export type { ArchitectureContextState }
export function useArchitectureContext(projectId: number | null, commitHash: string | null, revision = "ready") {
  const [state, setState] = useState<ArchitectureContextState>({ status: "idle" })
  const valid = projectId !== null && commitHash !== null && /^[a-fA-F0-9]{40}$/.test(commitHash)

  useEffect(() => {
    if (!valid) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setState((current) => (current.status === "idle" ? current : { status: "idle" }))
      return
    }
    const controller = new AbortController()
    setState({ status: "loading" })
    getArchitectureContextContent(projectId!, commitHash!, controller.signal).then(
      (context) => { if (!controller.signal.aborted) setState({ status: "ready", context }) },
      () => { if (!controller.signal.aborted) setState({ status: "error" }) },
    )
    return () => controller.abort()
  }, [projectId, commitHash, valid, revision])

  return state
}
