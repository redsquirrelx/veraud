import { afterEach, describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { Dock } from "./dock.tsx"
import { ToastProvider } from "./toasts.tsx"; import { useToasts } from "./use-toasts.ts"
import { AgentExecutionsProvider } from "../shared/agent-monitor/index.ts"

const realFetch = globalThis.fetch
const realWebSocket = globalThis.WebSocket

class FakeSocket {
  addEventListener() {}
  close() {}
}

type Listener = (event: { data: string }) => void

class PushSocket {
  static instances: PushSocket[] = []
  listeners: Record<string, Listener[]> = {}
  url: string

  constructor(url: string) {
    this.url = url
    PushSocket.instances.push(this)
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

  close() {}
}

afterEach(() => {
  globalThis.fetch = realFetch
  globalThis.WebSocket = realWebSocket
  PushSocket.instances = []
})

function PushButton() {
  const { pushToast } = useToasts()
  return (
    <button type="button" onClick={() => pushToast("success", "hello dock")}>
      push
    </button>
  )
}

describe("Dock", () => {
  it("shows live tasks and pushed toasts together", async () => {
    globalThis.fetch = (async () => {
      return new Response(JSON.stringify([
        { id: 1, projectId: 2, repositoryOwner: "acme", repositoryName: "Demo", description: "pulling acme/Demo", status: "Running", exitCode: null },
      ]), { status: 200 })
    }) as typeof fetch
    globalThis.WebSocket = FakeSocket as unknown as typeof WebSocket

    render(
      <ToastProvider>
        <PushButton />
        <Dock />
      </ToastProvider>
    )

    expect(await screen.findByText("pulling acme/Demo")).toBeDefined()

    await userEvent.click(screen.getByRole("button", { name: "push" }))

    expect(await screen.findByText("hello dock")).toBeDefined()
  })

  it("shows agent runs arriving over the socket", async () => {
    globalThis.fetch = (async () => {
      return new Response(JSON.stringify([]), { status: 200 })
    }) as typeof fetch
    globalThis.WebSocket = PushSocket as unknown as typeof WebSocket

    render(
      <ToastProvider>
        <AgentExecutionsProvider>
          <Dock />
        </AgentExecutionsProvider>
      </ToastProvider>
    )

    expect(screen.queryByText("analyzer run #11")).toBeNull()

    // Dock opens one socket for tasks and one for agents; broadcast to both.
    for (const socket of PushSocket.instances) {
      socket.push({
        type: "agent-execution.opened",
        execution: {
          id: 11,
          evaluationId: 7,
          agentType: "analyzer",
          status: "Waiting",
          result: null,
          error: null,
          inputTokens: null,
          outputTokens: null,
          createdAt: "2026-01-01",
          startedAt: null,
          finishedAt: null,
        },
      })
    }

    expect(await screen.findByText("analyzer run #11")).toBeDefined()
    expect(screen.getByText("Agent runs (1)")).toBeDefined()
  })
})
