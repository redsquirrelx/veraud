import { useEffect, useState, type ReactNode } from "react"
import { backendWsUrl, type AgentExecution } from "../../infrastructure/http-client/httpClient.ts"
import { AgentExecutionsContext } from "./useAgentExecutions.ts"

interface AgentExecutionEvent {
  type: string
  execution: AgentExecution
}

function isAgentEvent(data: unknown): data is AgentExecutionEvent {
  if (typeof data !== "object" || data === null) {
    return false
  }
  const event = data as { type?: unknown; execution?: unknown }
  if (event.type !== "agent-execution.opened" && event.type !== "agent-execution.updated") {
    return false
  }
  const execution = event.execution as { id?: unknown } | null
  return typeof execution?.id === "number"
}

export function AgentExecutionsProvider({ children, retryMs = 3000 }: { children: ReactNode; retryMs?: number }) {
  const [executions, setExecutions] = useState<AgentExecution[]>([])

  useEffect(() => {
    let alive = true
    let socket: WebSocket | null = null
    let retry: ReturnType<typeof setTimeout> | null = null

    function handleMessage(event: MessageEvent) {
      if (!alive) {
        return
      }
      let data: unknown
      try {
        data = JSON.parse(String(event.data))
      } catch {
        return
      }
      if (!isAgentEvent(data)) {
        return
      }
      setExecutions((current) => {
        const index = current.findIndex((execution) => execution.id === data.execution.id)
        if (index === -1) {
          return [...current, data.execution]
        }
        const next = [...current]
        next[index] = data.execution
        return next
      })
    }

    function schedule() {
      if (!alive) {
        return
      }
      retry = setTimeout(() => void connect(), retryMs)
    }

    function connect() {
      if (!alive) {
        return
      }
      try {
        socket = new WebSocket(backendWsUrl())
      } catch {
        schedule()
        return
      }
      socket.addEventListener("message", handleMessage)
      socket.addEventListener("close", schedule)
      socket.addEventListener("error", () => socket?.close())
    }

    connect()

    return () => {
      alive = false
      if (retry !== null) {
        clearTimeout(retry)
      }
      const current = socket
      if (current === null) {
        return
      }
      if (current.readyState === WebSocket.CONNECTING) {
        current.addEventListener("open", () => current.close(), { once: true })
      } else {
        current.close()
      }
    }
  }, [retryMs])

  return <AgentExecutionsContext.Provider value={executions}>{children}</AgentExecutionsContext.Provider>
}
