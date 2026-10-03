import { afterEach, describe, expect, it } from "vitest"
import { act, renderHook } from "@testing-library/react"
import { StrictMode, type ReactNode } from "react"
import { useRegisterProject } from "./useRegisterProject.ts"

const realFetch = globalThis.fetch

function StrictModeWrapper({ children }: { children: ReactNode }) {
  return <StrictMode>{children}</StrictMode>
}

afterEach(() => {
  globalThis.fetch = realFetch
})

function stubFetch(status: number, body: unknown) {
  globalThis.fetch = (async () => {
    return new Response(JSON.stringify(body), { status })
  }) as typeof fetch
}

describe("useRegisterProject", () => {
  it("registers and reports success", async () => {
    stubFetch(201, { id: 1, repositoryOwner: "acme", repositoryName: "Demo", status: "QUEUED" })
    const { result } = renderHook(() => useRegisterProject())

    act(() => {
      result.current.changeUrl("https://github.com/acme/Demo")
    })
    await act(async () => {
      await result.current.register()
    })

    expect(result.current.state).toBe("success")
    expect(result.current.message).toContain("acme/Demo")
    expect(result.current.project?.id).toBe(1)
  })

  it("clears the input on submit and cools down for 2s", async () => {
    stubFetch(201, { id: 1, repositoryOwner: "acme", repositoryName: "Demo", status: "QUEUED" })
    const { result } = renderHook(() => useRegisterProject(), { wrapper: StrictModeWrapper })

    act(() => {
      result.current.changeUrl("https://github.com/acme/Demo")
    })
    await act(async () => {
      await result.current.register()
    })

    expect(result.current.url).toBe("")
    expect(result.current.cooling).toBe(true)

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 2100))
    })
    expect(result.current.cooling).toBe(false)
  }, 10000)

  it("queues a second submit while the first is still running", async () => {
    let calls = 0
    globalThis.fetch = (() => new Promise<Response>((resolve) => {
      calls += 1
      const id = calls
      setTimeout(() => {
        resolve(new Response(
          JSON.stringify({ id, repositoryOwner: "acme", repositoryName: `R${id}`, status: "QUEUED" }),
          { status: 201 }
        ))
      }, 2500)
    })) as typeof fetch
    const { result } = renderHook(() => useRegisterProject())

    act(() => {
      result.current.changeUrl("https://github.com/acme/A")
    })
    const first = result.current.register()

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 2100))
    })
    expect(result.current.cooling).toBe(false)

    act(() => {
      result.current.changeUrl("https://github.com/acme/B")
    })
    const second = result.current.register()

    await act(async () => {
      await Promise.all([first, second])
    })

    expect(calls).toBe(2)
    expect(result.current.state).toBe("success")
    expect(result.current.message).toContain("acme/R2")
  }, 15000)

  it("does nothing without a url", async () => {
    const { result } = renderHook(() => useRegisterProject())

    await act(async () => {
      await result.current.register()
    })

    expect(result.current.state).toBe("idle")
  })

  it("reports timeouts from browsers and node", async () => {
    for (const name of ["AbortError", "TimeoutError"]) {
      const failure = new DOMException("timed out", name)
      globalThis.fetch = (async () => {
        throw failure
      }) as typeof fetch
      const { result } = renderHook(() => useRegisterProject())

      act(() => {
        result.current.changeUrl("https://github.com/acme/Big")
      })
      await act(async () => {
        await result.current.register()
      })

      expect(result.current.state).toBe("error")
      expect(result.current.message).toBe("The request took too long and was cancelled")
    }
  })

  it("reports the backend message on error", async () => {
    stubFetch(422, { message: "Repository is not accessible" })
    const { result } = renderHook(() => useRegisterProject())

    act(() => {
      result.current.changeUrl("https://github.com/acme/Gone")
    })
    await act(async () => {
      await result.current.register()
    })

    expect(result.current.state).toBe("error")
    expect(result.current.message).toBe("Repository is not accessible")
    expect(result.current.project).toBeNull()
  })

  it("resets back to idle", async () => {
    stubFetch(422, { message: "nope" })
    const { result } = renderHook(() => useRegisterProject())

    act(() => {
      result.current.changeUrl("https://github.com/acme/Gone")
    })
    await act(async () => {
      await result.current.register()
    })
    act(() => {
      result.current.reset()
    })

    expect(result.current.state).toBe("idle")
    expect(result.current.message).toBe("")
  })
})
