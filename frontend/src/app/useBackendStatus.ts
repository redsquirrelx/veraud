import { useEffect, useState } from "react"

const backendUrl = import.meta.env.VITE_BACKEND_URL ?? "http://localhost:7501"

export type BackendStatus = "online" | "offline"

async function checkStatus(signal: AbortSignal): Promise<boolean> {
  try {
    const response = await fetch(`${backendUrl}/status`, { signal })
    return response.ok
  } catch {
    return false
  }
}

export function useBackendStatus(intervalMs = 2000): BackendStatus {
  const [status, setStatus] = useState<BackendStatus>("offline")

  useEffect(() => {
    let alive = true
    const controller = new AbortController()

    async function poll() {
      const ok = await checkStatus(controller.signal)
      if (alive) {
        setStatus(ok ? "online" : "offline")
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

  return status
}
