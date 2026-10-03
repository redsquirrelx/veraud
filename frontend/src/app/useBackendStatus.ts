import { useEffect, useState } from "react"

const backendUrl = import.meta.env.VITE_BACKEND_URL ?? "http://localhost:7501"

export type ServiceStatus = "online" | "offline" | "unknown"

interface StatusResponse {
  agentServer?: string
}

async function checkStatus(signal: AbortSignal): Promise<{ backend: boolean; agent: string }> {
  try {
    const response = await fetch(`${backendUrl}/status`, { signal })
    if (!response.ok) {
      return { backend: false, agent: "unknown" }
    }
    const body = (await response.json()) as StatusResponse
    return { backend: true, agent: body.agentServer ?? "unknown" }
  } catch {
    return { backend: false, agent: "unknown" }
  }
}

function toAgentStatus(value: string): ServiceStatus {
  if (value === "online" || value === "offline") {
    return value
  }
  return "unknown"
}

export function useBackendStatus(intervalMs = 2000): { backend: ServiceStatus; agent: ServiceStatus } {
  const [backend, setBackend] = useState<ServiceStatus>("offline")
  const [agent, setAgent] = useState<ServiceStatus>("unknown")

  useEffect(() => {
    let alive = true
    const controller = new AbortController()

    async function poll() {
      const result = await checkStatus(controller.signal)
      if (alive) {
        setBackend(result.backend ? "online" : "offline")
        setAgent(toAgentStatus(result.agent))
      }
    }

    void poll()
    const timer = setInterval(() => void poll(), intervalMs)

    return () => {
      alive = false
      controller.abort()
      clearInterval(timer)
    }
  }, [intervalMs])

  return { backend, agent }
}
