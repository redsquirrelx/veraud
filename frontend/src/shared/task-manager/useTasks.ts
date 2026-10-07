import { useEffect, useState } from "react"
import { backendWsUrl, listActiveTasks, type ActiveTask } from "../../infrastructure/http-client/httpClient.ts"

interface TaskUpdatedEvent {
  type: string
  task: ActiveTask
}

function isTaskEvent(data: unknown): data is TaskUpdatedEvent {
  if (typeof data !== "object" || data === null) {
    return false
  }
  return (data as { type?: unknown }).type === "task.updated"
}

export function useTasks(retryMs = 3000) {
  const [tasks, setTasks] = useState<ActiveTask[]>([])

  useEffect(() => {
    let alive = true
    let socket: WebSocket | null = null
    let retry: ReturnType<typeof setTimeout> | null = null

    async function load() {
      try {
        const initial = await listActiveTasks()
        if (alive) {
          setTasks(initial)
        }
      } catch {
        // backend down, retry through the socket loop
      }
    }

    function handleMessage(event: MessageEvent) {
      if (!alive) {
        return
      }      let data: unknown
      try {
        data = JSON.parse(String(event.data))
      } catch {
        return
      }
      if (!isTaskEvent(data)) {
        return
      }
      setTasks((current) => {
        const index = current.findIndex((task) => task.id === data.task.id)
        if (index === -1) {
          return [...current, data.task]
        }
        const next = [...current]
        next[index] = data.task
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
      socket.addEventListener("open", () => void load())
      socket.addEventListener("message", handleMessage)
      socket.addEventListener("close", schedule)
      socket.addEventListener("error", () => socket?.close())
    }

    void load()
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

  return tasks
}
