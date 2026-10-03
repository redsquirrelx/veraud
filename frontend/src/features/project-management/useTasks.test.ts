import { afterEach, describe, expect, it } from "vitest"
import { renderHook, waitFor } from "@testing-library/react"
import { useTasks } from "./useTasks.ts"

const realFetch = globalThis.fetch
const realWebSocket = globalThis.WebSocket

type Listener = (event: { data: string }) => void

class FakeSocket {
  static instances: FakeSocket[] = []
  listeners: Record<string, Listener[]> = {}
  url: string

  constructor(url: string) {
    this.url = url
    FakeSocket.instances.push(this)
  }

  addEventListener(type: string, listener: Listener) {
    if (this.listeners[type] === undefined) {
      this.listeners[type] = []
    }
    this.listeners[type].push(listener)
  }

  push(data: unknown) {
    for (const listener of this.listeners["message"] ?? []) {
      listener({ data: JSON.stringify(data) })
    }
  }

  emit(type: string) {
    for (const listener of this.listeners[type] ?? []) {
      listener({ data: "" })
    }
  }

  close() {}
}

afterEach(() => {
  globalThis.fetch = realFetch
  globalThis.WebSocket = realWebSocket
  FakeSocket.instances = []
})

describe("useTasks", () => {
  it("loads initial tasks and follows ws updates", async () => {
    globalThis.fetch = (async () => {
      return new Response(JSON.stringify([
        { id: 1, projectId: 2, repositoryOwner: "acme", repositoryName: "Demo", description: "cloning acme/Demo", status: "Queued", exitCode: null },
      ]), { status: 200 })
    }) as typeof fetch
    globalThis.WebSocket = FakeSocket as unknown as typeof WebSocket

    const { result } = renderHook(() => useTasks())

    await waitFor(() => {
      expect(result.current.length).toBe(1)
    })

    const socket = FakeSocket.instances[0]
    socket?.push({ type: "task.updated", task: { id: 2, projectId: 3, repositoryOwner: "acme", repositoryName: "Other", description: "cloning acme/Other", status: "Running", exitCode: null } })

    await waitFor(() => {
      expect(result.current.length).toBe(2)
    })

    socket?.push({ type: "task.updated", task: { id: 1, projectId: 2, repositoryOwner: "acme", repositoryName: "Demo", description: "cloning acme/Demo", status: "Succeded", exitCode: 0 } })

    await waitFor(() => {
      expect(result.current.map((task) => task.id)).toEqual([1, 2])
    })
    await waitFor(() => {
      expect(result.current.find((task) => task.id === 1)?.status).toBe("Succeded")
    })
  })

  it("starts empty when the backend is down", async () => {
    globalThis.fetch = (async () => {
      throw new Error("down")
    }) as typeof fetch
    globalThis.WebSocket = FakeSocket as unknown as typeof WebSocket

    const { result } = renderHook(() => useTasks())

    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(result.current).toEqual([])
  })

  it("reconnects and reloads after the socket closes", async () => {
    globalThis.fetch = (async () => {
      return new Response(JSON.stringify([]), { status: 200 })
    }) as typeof fetch
    globalThis.WebSocket = FakeSocket as unknown as typeof WebSocket

    renderHook(() => useTasks(30))

    await waitFor(() => {
      expect(FakeSocket.instances.length).toBe(1)
    })

    FakeSocket.instances[0]?.emit("close")

    await waitFor(() => {
      expect(FakeSocket.instances.length).toBe(2)
    })
  })
})
