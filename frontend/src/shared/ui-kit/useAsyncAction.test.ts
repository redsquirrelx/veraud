import { describe, expect, it, vi } from "vitest"
import { act, renderHook } from "@testing-library/react"
import { useAsyncAction } from "./useAsyncAction.ts"

function deferred() {
  let resolve = () => {}
  const promise = new Promise<void>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

describe("useAsyncAction", () => {
  it("is loading while the action runs", async () => {
    const gate = deferred()
    const { result } = renderHook(() => useAsyncAction(() => gate.promise))

    expect(result.current.loading).toBe(false)

    let run: Promise<void> | null = null
    act(() => {
      run = result.current.run()
    })
    expect(result.current.loading).toBe(true)

    await act(async () => {
      gate.resolve()
      await run
    })
    expect(result.current.loading).toBe(false)
  })

  it("ignores a second run while busy", async () => {
    const action = vi.fn(async () => {})
    const { result } = renderHook(() => useAsyncAction(action))

    await act(async () => {
      await Promise.all([result.current.run(), result.current.run()])
    })

    expect(action).toHaveBeenCalledTimes(1)
  })

  it("settles quietly after unmount", async () => {
    const gate = deferred()
    const { result, unmount } = renderHook(() => useAsyncAction(() => gate.promise))

    act(() => {
      void result.current.run()
    })
    unmount()

    await act(async () => {
      gate.resolve()
    })
  })

  it("surfaces action errors and stops loading", async () => {
    const { result } = renderHook(() =>
      useAsyncAction(async () => {
        throw new Error("Clone failed")
      })
    )

    await act(async () => {
      await result.current.run()
    })

    expect(result.current.loading).toBe(false)
    expect(result.current.error).toBe("Clone failed")
  })

  it("times out instead of blocking forever and allows retry", async () => {
    const gate = deferred()
    const { result } = renderHook(() => useAsyncAction(() => gate.promise, { timeoutMs: 20 }))

    await act(async () => {
      await result.current.run()
    })

    expect(result.current.loading).toBe(false)
    expect(result.current.error).toBe("Timed out after 20ms")

    gate.resolve()
    await act(async () => {
      await result.current.run()
    })
    expect(result.current.loading).toBe(false)
    expect(result.current.error).toBeNull()
  })
})
