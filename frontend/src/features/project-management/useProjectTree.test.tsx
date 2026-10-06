import { afterEach, describe, expect, it } from "vitest"
import { act, render, renderHook, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { useEffect } from "react"
import { DirectoryTree } from "../../shared/ui-kit/index.ts"
import { useProjectTree } from "./useProjectTree.ts"

const realFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = realFetch
})

function stubFiles(files: string[] | "fail") {
  let calls = 0
  globalThis.fetch = (async () => {
    calls += 1
    if (files === "fail") {
      return new Response(JSON.stringify({ message: "Could not list the files of acme/Demo" }), { status: 422 })
    }
    return new Response(JSON.stringify({ files, taskId: calls }), { status: 200 })
  }) as typeof fetch
  return () => calls
}

describe("useProjectTree", () => {
  it("does nothing until the caller refreshes", () => {
    const calls = stubFiles(["README.md"])

    const { result } = renderHook(() => useProjectTree(2, "Demo"))

    expect(calls()).toBe(0)
    expect(result.current.tree).toBeNull()
  })

  it("builds the tree from the listed files", async () => {
    const calls = stubFiles(["src/app.py", "README.md"])
    const { result } = renderHook(() => useProjectTree(2, "Demo"))

    act(() => {
      result.current.refresh()
    })

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(calls()).toBe(1)
    expect(result.current.tree?.name).toBe("Demo")
    expect(result.current.tree?.children?.map((child) => child.name)).toEqual(["src", "README.md"])
  })

  it("keeps the tree visible while refreshing", async () => {
    let release = () => {}
    let calls = 0
    globalThis.fetch = (async () => {
      calls += 1
      if (calls === 1) {
        return new Response(JSON.stringify({ files: ["README.md"], taskId: 1 }), { status: 200 })
      }
      return new Promise<Response>((resolve) => {
        release = () => resolve(new Response(JSON.stringify({ files: ["a.ts"], taskId: 2 }), { status: 200 }))
      })
    }) as typeof fetch

    const { result } = renderHook(() => useProjectTree(2, "Demo"))

    act(() => {
      result.current.refresh()
    })
    await waitFor(() => expect(result.current.tree).not.toBeNull())

    act(() => {
      result.current.refresh()
    })

    expect(result.current.loading).toBe(true)
    expect(result.current.tree?.children?.map((child) => child.name)).toEqual(["README.md"])

    release()
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.tree?.children?.map((child) => child.name)).toEqual(["a.ts"])
  })

  it("hides a tree that belongs to another project", async () => {
    stubFiles(["README.md"])
    const { result, rerender } = renderHook(({ id }) => useProjectTree(id, "Demo"), { initialProps: { id: 2 } })

    act(() => {
      result.current.refresh()
    })
    await waitFor(() => expect(result.current.tree).not.toBeNull())

    rerender({ id: 3 })

    expect(result.current.tree).toBeNull()
  })

  it("surfaces the backend error and clears the tree", async () => {
    stubFiles("fail")
    const { result } = renderHook(() => useProjectTree(2, "Demo"))

    act(() => {
      result.current.refresh()
    })

    await waitFor(() => expect(result.current.error).toBe("Could not list the files of acme/Demo"))
    expect(result.current.tree).toBeNull()
  })

  it("tolerates a malformed payload", async () => {
    globalThis.fetch = (async () => new Response(JSON.stringify({}), { status: 200 })) as typeof fetch
    const { result } = renderHook(() => useProjectTree(2, "Demo"))

    act(() => {
      result.current.refresh()
    })

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.tree?.children).toEqual([])
  })

  it("does nothing without a project", () => {
    const calls = stubFiles(["README.md"])
    const { result } = renderHook(() => useProjectTree(null, ""))

    act(() => {
      result.current.refresh()
    })

    expect(calls()).toBe(0)
    expect(result.current.tree).toBeNull()
  })
})

describe("useProjectTree inside a view", () => {
  it("releases the tree when the view unmounts", async () => {
    stubFiles(["README.md"])

    function Harness({ id }: { id: number | null }) {
      const files = useProjectTree(id, "Demo")
      const refreshFiles = files.refresh

      useEffect(() => {
        refreshFiles()
      }, [refreshFiles])

      return <span>{files.tree === null ? "empty" : (files.tree.name as string)}</span>
    }

    const { unmount } = render(<Harness id={2} />)

    await waitFor(() => expect(screen.getByText("Demo")).toBeDefined())
    unmount()
    expect(document.body.textContent).toBe("")
  })

  it("lets the auditor filter the loaded tree", async () => {
    stubFiles(["src/app.py", "src/lib.ts", "README.md"])

    function Harness() {
      const files = useProjectTree(2, "Demo")
      const refreshFiles = files.refresh

      useEffect(() => {
        refreshFiles()
      }, [refreshFiles])

      if (files.tree === null) {
        return <p>loading</p>
      }
      return <DirectoryTree tree={files.tree} initialExpanded={["Demo/src"]} />
    }

    render(<Harness />)

    await waitFor(() => expect(screen.getByText("app.py")).toBeDefined())

    await userEvent.type(screen.getByPlaceholderText("File or folder name"), "lib")

    expect(screen.getByText("lib.ts")).toBeDefined()
    expect(screen.queryByText("README.md")).toBeNull()
  })
})
