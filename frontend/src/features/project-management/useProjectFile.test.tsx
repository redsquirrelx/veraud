import { afterEach, describe, expect, it } from "vitest"
import { act, renderHook, waitFor } from "@testing-library/react"
import { useProjectFile } from "./useProjectFile.ts"

const realFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = realFetch
})

function stubFile(content: string | "fail", seen: string[] = []) {
  globalThis.fetch = (async (input: unknown, init?: RequestInit) => {
    const url = String(input)
    const body = init?.body === undefined ? {} : (JSON.parse(String(init.body)) as { path?: string })
    seen.push(`${url} ${body.path ?? ""}`)
    if (content === "fail") {
      return new Response(JSON.stringify({ message: "File nope.txt does not exist" }), { status: 422 })
    }
    return new Response(JSON.stringify({ path: body.path, content, size: content.length }), { status: 200 })
  }) as typeof fetch
}

describe("useProjectFile", () => {
  it("fetches nothing until a file is opened", () => {
    const seen: string[] = []
    stubFile("hello", seen)
    const { result } = renderHook(() => useProjectFile(2))

    expect(seen).toEqual([])
    expect(result.current.file).toBeNull()
  })

  it("loads the file content on open", async () => {
    const seen: string[] = []
    stubFile("hello", seen)
    const { result } = renderHook(() => useProjectFile(2))

    act(() => {
      result.current.open("src/app.ts")
    })

    expect(result.current.loading).toBe(true)
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.file).toEqual({ path: "src/app.ts", content: "hello", size: 5 })
    expect(seen.some((entry) => entry.includes("/api/projects/2/file"))).toBe(true)
  })

  it("ignores a stale response when opening twice", async () => {
    const seen: string[] = []
    let releaseFirst = () => {}
    let calls = 0
    globalThis.fetch = (async (_input: unknown, init?: RequestInit) => {
      calls += 1
      const body = (JSON.parse(String(init?.body)) as { path?: string })
      seen.push(body.path ?? "")
      if (calls === 1) {
        return new Promise<Response>((resolve) => {
          releaseFirst = () => resolve(new Response(JSON.stringify({ path: body.path, content: "first", size: 5 }), { status: 200 }))
        })
      }
      return new Response(JSON.stringify({ path: body.path, content: "second", size: 6 }), { status: 200 })
    }) as typeof fetch
    const { result } = renderHook(() => useProjectFile(2))

    act(() => {
      result.current.open("first.ts")
    })
    act(() => {
      result.current.open("second.ts")
    })
    releaseFirst()

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.file?.path).toBe("second.ts")
    expect(result.current.file?.content).toBe("second")
  })

  it("surfaces backend errors without content", async () => {
    stubFile("fail")
    const { result } = renderHook(() => useProjectFile(2))

    act(() => {
      result.current.open("nope.txt")
    })

    await waitFor(() => expect(result.current.error).toBe("File nope.txt does not exist"))
    expect(result.current.file).toBeNull()
  })

  it("clears the preview when the project changes", async () => {
    stubFile("hello")
    const { result, rerender } = renderHook(({ id }) => useProjectFile(id), { initialProps: { id: 2 } })

    act(() => {
      result.current.open("a.ts")
    })
    await waitFor(() => expect(result.current.file).not.toBeNull())

    rerender({ id: 3 })

    expect(result.current.file).toBeNull()
    expect(result.current.error).toBe("")
  })

  it("clears the preview and invalidates in-flight loads", async () => {
    let release = () => {}
    globalThis.fetch = (async () => {
      return new Promise<Response>((resolve) => {
        release = () => resolve(new Response(JSON.stringify({ path: "a.ts", content: "hello", size: 5 }), { status: 200 }))
      })
    }) as typeof fetch
    const { result } = renderHook(() => useProjectFile(2))

    act(() => {
      result.current.open("a.ts")
    })
    expect(result.current.loading).toBe(true)

    act(() => {
      result.current.clear()
    })

    expect(result.current.file).toBeNull()
    expect(result.current.loading).toBe(false)

    release()
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.file).toBeNull()
  })

  it("does nothing without a project", () => {
    const seen: string[] = []
    stubFile("hello", seen)
    const { result } = renderHook(() => useProjectFile(null))

    act(() => {
      result.current.open("a.ts")
    })

    expect(seen).toEqual([])
  })
})
