import type { ReactNode } from "react"
import { I18nextProvider } from "react-i18next"
import { AgentExecutionsProvider } from "../shared/agent-monitor/agentMonitor.tsx"
import { i18n } from "../shared/i18n/index.ts"

export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <I18nextProvider i18n={i18n}>
      <AgentExecutionsProvider>{children}</AgentExecutionsProvider>
    </I18nextProvider>
  )
}
