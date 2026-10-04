import { afterEach, describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { Dock } from "./dock.tsx"
import { ToastProvider } from "./toasts.tsx"; import { useToasts } from "./use-toasts.ts"

const realFetch = globalThis.fetch
const realWebSocket = globalThis.WebSocket

class FakeSocket {
  addEventListener() {}
  close() {}
}

afterEach(() => {
  globalThis.fetch = realFetch
  globalThis.WebSocket = realWebSocket
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
})
