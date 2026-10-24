import { useEffect, useState } from "react"
import { listAgentSettings, type AgentSettings } from "../../infrastructure/http-client/httpClient.ts"
import { useAgentExecutions } from "../agent-monitor/useAgentExecutions.ts"
import { AuditStatusDrawer } from "./AuditStatusDrawer.tsx"
import { executionAudits } from "./executionAudits.ts"

/** Uses the existing restored WebSocket feed; the drawer remains presentational. */
export function LiveAuditMonitor() {
  const executions = useAgentExecutions()
  const [catalog, setCatalog] = useState<AgentSettings[]>([])
  const hasExecutions = executions.length > 0
  useEffect(() => {
    if (!hasExecutions) return
    const controller = new AbortController()
    listAgentSettings(controller.signal).then((agents) => {
      if (!controller.signal.aborted) setCatalog(agents)
    }).catch(() => { /* HTTP execution context remains usable while catalog loading is unavailable. */ })
    return () => controller.abort()
  }, [hasExecutions])
  return <AuditStatusDrawer audits={executionAudits(executions, catalog)} />
}
