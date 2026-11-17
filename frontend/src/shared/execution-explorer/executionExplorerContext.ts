import { createContext, useContext } from "react"

export interface ExecutionExplorerContextValue {
  /** Open the explorer; pass an execution id to preselect it (mock ids only until the real adapter lands). */
  openExplorer: (executionId?: string) => void
  close: () => void
  open: boolean
  executionId: string | null
}

export const ExecutionExplorerContext = createContext<ExecutionExplorerContextValue>({
  openExplorer: () => {},
  close: () => {},
  open: false,
  executionId: null,
})

/** App-wide handle for opening the Execution Explorer. */
export function useExecutionExplorer() {
  return useContext(ExecutionExplorerContext)
}
