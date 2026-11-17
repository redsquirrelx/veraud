import { useCallback, useMemo, useState, type ReactNode } from "react"
import { ExecutionExplorerContext, type ExecutionExplorerContextValue } from "./executionExplorerContext.ts"
import { ExecutionExplorerModal } from "./ExecutionExplorerModal.tsx"

/** Owns the single app-wide explorer instance and exposes openExplorer to the tree.
 *  A session counter remounts the modal on every open, so each opening starts
 *  from a clean selection, filters and mobile panel — preselected execution
 *  included. */
export function ExecutionExplorerProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const [executionId, setExecutionId] = useState<string | null>(null)
  const [session, setSession] = useState(0)

  const openExplorer = useCallback((id?: string) => {
    setExecutionId(id ?? null)
    setSession((current) => current + 1)
    setOpen(true)
  }, [])

  const close = useCallback(() => setOpen(false), [])

  const value = useMemo<ExecutionExplorerContextValue>(
    () => ({ open, executionId, openExplorer, close }),
    [open, executionId, openExplorer, close],
  )

  return (
    <ExecutionExplorerContext.Provider value={value}>
      {children}
      <ExecutionExplorerModal key={session} open={open} initialExecutionId={executionId} onClose={close} />
    </ExecutionExplorerContext.Provider>
  )
}
