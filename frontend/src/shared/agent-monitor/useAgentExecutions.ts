import { createContext, useContext } from "react"
import type { AgentExecution } from "../../infrastructure/http-client/httpClient.ts"

export const AgentExecutionsContext = createContext<AgentExecution[]>([])

export function useAgentExecutions(): AgentExecution[] {
  return useContext(AgentExecutionsContext)
}
