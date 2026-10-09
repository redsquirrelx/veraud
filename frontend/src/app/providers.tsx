import type { ReactNode } from "react"
import { AgentExecutionsProvider } from "../shared/agent-monitor/agentMonitor.tsx"

export function AppProviders({ children }: { children: ReactNode }) {
  return <AgentExecutionsProvider>{children}</AgentExecutionsProvider>
}
