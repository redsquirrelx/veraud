import { afterEach, describe, expect, it } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { ProjectDetailPage } from "./ProjectDetailPage.tsx"
import { ToastProvider } from "../../app/toasts.tsx"
import { Dock } from "../../app/dock.tsx"

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

const rows = [
  { id: 2, repositoryOwner: "acme", repositoryName: "Demo", status: "READY", registeredAt: "2026-01-01", lastSyncedAt: "2026-01-02", branch: null, commitHash: null },
]

const gitBranches = { branches: ["main"], currentBranch: "main", detachedHash: null, taskId: 1 }
const gitCommits = {
  branch: "main",
  commits: [{ commitHash: "a".repeat(40), subject: "init" }],
  limit: 30,
  offset: 0,
  taskId: 2,
}

const gitTree = { files: ["src/index.ts", "README.md"], taskId: 6 }

function stubFetch(handler: (url: string, init?: RequestInit) => Response | Promise<Response>) {
  globalThis.fetch = (async (input: unknown, init?: RequestInit) => {
    return handler(String(input), init)
  }) as typeof fetch
  globalThis.WebSocket = FakeSocket as unknown as typeof WebSocket
}

function gitResponse(url: string, init?: RequestInit): Response | null {
  if (url.includes("/git/branches")) {
    return new Response(JSON.stringify(gitBranches), { status: 200 })
  }
  if (url.includes("/git/tree")) {
    return new Response(JSON.stringify(gitTree), { status: 200 })
  }
  if (url.includes("/git/log")) {
    return new Response(JSON.stringify(gitCommits), { status: 200 })
  }
  if (url.includes("/git/checkout-branch")) {
    return new Response(JSON.stringify({ branch: "main", taskId: 5 }), { status: 200 })
  }
  if (url.includes("/git/checkout")) {
    const body = init?.body === undefined ? {} : (JSON.parse(String(init.body)) as { commitHash?: string })
    return new Response(JSON.stringify({ commitHash: body.commitHash ?? "a".repeat(40), taskId: 3 }), { status: 200 })
  }
  if (url.includes("/git/rev-parse")) {
    return new Response(JSON.stringify({ branch: "main", commitHash: "a".repeat(40), taskId: 4 }), { status: 200 })
  }
  if (url.includes("/api/projects/") && url.endsWith("/file")) {
    const body = init?.body === undefined ? {} : (JSON.parse(String(init.body)) as { path?: string })
    return new Response(JSON.stringify({ path: body.path ?? "", content: `# ${body.path ?? ""}\n`, size: 10 }), { status: 200 })
  }
  return null
}

function stubProjects(options?: { treePending?: boolean, treeFiles?: string[] }) {
  let release = () => {}
  const seen: string[] = []
  stubFetch((url, init) => {
    if (url.includes("/api/tasks/active")) {
      return new Response(JSON.stringify([]), { status: 200 })
    }
    if (url.includes("/git/tree")) {
      seen.push(url)
      if (options?.treePending === true) {
        return new Promise<Response>((resolve) => {
          release = () => resolve(new Response(JSON.stringify({ files: options?.treeFiles ?? gitTree.files, taskId: 6 }), { status: 200 }))
        })
      }
    }
    return gitResponse(url, init) ?? new Response(JSON.stringify(rows), { status: 200 })
  })
  return { seen, release: () => release() }
}

function renderDetail(entry: string) {
  render(
    <MemoryRouter initialEntries={[entry]}>
      <ToastProvider>
        <Routes>
          <Route path="projects/:id" element={<ProjectDetailPage />} />
        </Routes>
        <Dock />
      </ToastProvider>
    </MemoryRouter>
  )
}

describe("ProjectDetailPage", () => {
  it("shows the project header with sidebar", async () => {
    stubProjects()
    renderDetail("/projects/2")

    expect(await screen.findByText("acme/Demo")).toBeDefined()
    expect(screen.getByText("READY")).toBeDefined()
    expect(screen.getByText("Project")).toBeDefined()
    expect(screen.getByText(`Last synced ${new Date("2026-01-02").toLocaleDateString()}`)).toBeDefined()
    expect(screen.getByRole("button", { name: "Sync" })).toBeDefined()

    const link = screen.getByRole("link", { name: "Open on GitHub" })
    expect(link.getAttribute("href")).toBe("https://github.com/acme/Demo")
    expect(link.getAttribute("target")).toBe("_blank")
    expect(link.getAttribute("rel")).toContain("noreferrer")
  })

  it("shows not found for unknown projects", async () => {
    stubProjects()
    renderDetail("/projects/99")

    expect(await screen.findByText("Project not found")).toBeDefined()
  })

  it("syncs on demand and refreshes the header", async () => {
    let branchCalls = 0
    stubFetch((url, init) => {
      if (url.includes("/sync")) {
        return new Response(
          JSON.stringify({ ...rows[0], status: "READY", lastSyncedAt: "2026-02-02" }),
          { status: 200 }
        )
      }
      if (url.includes("/api/tasks/active")) {
        return new Response(JSON.stringify([]), { status: 200 })
      }
      if (url.includes("/git/branches")) {
        branchCalls += 1
      }
      return gitResponse(url, init) ?? new Response(JSON.stringify(rows), { status: 200 })
    })
    renderDetail("/projects/2")

    await screen.findByText("acme/Demo")
    const callsBefore = branchCalls
    await userEvent.click(screen.getByRole("button", { name: "Sync" }))

    expect(await screen.findByText(`Last synced ${new Date("2026-02-02").toLocaleDateString()}`)).toBeDefined()
    expect(await screen.findByText("Project acme/Demo synced")).toBeDefined()
    expect(branchCalls).toBeGreaterThan(callsBefore)
  })

  it("shows the sync error and re-enables the button", async () => {
    stubFetch((url, init) => {
      if (url.includes("/sync")) {
        return new Response(JSON.stringify({ message: "Could not sync" }), { status: 422 })
      }
      if (url.includes("/api/tasks/active")) {
        return new Response(JSON.stringify([]), { status: 200 })
      }
      return gitResponse(url, init) ?? new Response(JSON.stringify(rows), { status: 200 })
    })
    renderDetail("/projects/2")

    await screen.findByText("acme/Demo")
    await userEvent.click(screen.getByRole("button", { name: "Sync" }))

    expect(await screen.findByRole("alert")).toBeDefined()
    expect(screen.getByText("Could not sync")).toBeDefined()
    expect(screen.getByRole("button", { name: "Sync" }).hasAttribute("disabled")).toBe(false)
  })

  it("shows running sync tasks in the menu", async () => {
    stubFetch((url, init) => {
      if (url.includes("/api/tasks/active")) {
        return new Response(JSON.stringify([
          { id: 5, projectId: 2, repositoryOwner: "acme", repositoryName: "Demo", description: "pulling acme/Demo", status: "Running", exitCode: null },
        ]), { status: 200 })
      }
      return gitResponse(url, init) ?? new Response(JSON.stringify(rows), { status: 200 })
    })
    renderDetail("/projects/2")

    expect(await screen.findByText("pulling acme/Demo")).toBeDefined()
  })

  it("shows a loading state and then the project files in the files section", async () => {
    const stub = stubProjects({ treePending: true })
    renderDetail("/projects/2")

    await screen.findByText("acme/Demo")
    await userEvent.click(screen.getByRole("button", { name: "Files" }))

    expect(await screen.findByText("Loading project files")).toBeDefined()

    stub.release()

    expect(await screen.findByText("src")).toBeDefined()
    expect(screen.getByText("README.md")).toBeDefined()
    expect(screen.queryByText("index.ts")).toBeNull()
    expect(stub.seen.length).toBe(1)

    const rowsInTree = screen.getByRole("tree").querySelectorAll("li")
    await userEvent.click(rowsInTree[1]?.querySelector("button") as HTMLElement)

    expect(await screen.findByText("index.ts")).toBeDefined()
  })

  it("previews a file right of the directories when selected", async () => {
    stubProjects()
    renderDetail("/projects/2")

    await screen.findByText("acme/Demo")
    await userEvent.click(screen.getByRole("button", { name: "Files" }))
    await screen.findByText("README.md")

    expect(screen.getByText("Select a file to preview")).toBeDefined()

    const fileButtons = Array.from(screen.getByRole("tree").querySelectorAll("li button"))
    const readme = fileButtons.find((button) => button.textContent?.includes("README.md"))
    if (readme === undefined) {
      throw new Error("README.md row not found")
    }
    await userEvent.click(readme)

    expect(await screen.findByText("# README.md")).toBeDefined()
    expect(screen.queryByText("Select a file to preview")).toBeNull()

    const split = document.querySelector(".ui-split")
    expect(split).not.toBeNull()
    const panes = split?.querySelectorAll(":scope > .ui-split-pane") ?? []
    expect(panes.length).toBe(2)
    expect(panes[0]?.querySelector(".directory-tree")).not.toBeNull()
    expect(panes[1]?.querySelector(".ui-code-viewer")).not.toBeNull()
    expect(document.querySelectorAll(".files-layout").length).toBe(0)
  })

  it("clears the file preview when the version changes", async () => {
    stubProjects()
    renderDetail("/projects/2")

    await screen.findByText("acme/Demo")
    await userEvent.click(screen.getByRole("button", { name: "Files" }))
    await screen.findByText("README.md")

    const fileButtons = Array.from(screen.getByRole("tree").querySelectorAll("li button"))
    const readme = fileButtons.find((button) => button.textContent?.includes("README.md"))
    if (readme === undefined) {
      throw new Error("README.md row not found")
    }
    await userEvent.click(readme)
    expect(await screen.findByText("# README.md")).toBeDefined()

    await userEvent.clear(screen.getByLabelText("Search items"))
    await userEvent.type(screen.getByLabelText("Search items"), `${"b".repeat(40)}{enter}`)

    expect(await screen.findByText("Version main at bbbbbbb applied")).toBeDefined()
    expect(screen.getByText("Select a file to preview")).toBeDefined()
    expect(screen.queryByText("# README.md")).toBeNull()
  })

  it("clears the file preview after a sync", async () => {
    let treeCalls = 0
    stubFetch((url, init) => {
      if (url.includes("/sync")) {
        return new Response(JSON.stringify({ ...rows[0], status: "READY", lastSyncedAt: "2026-03-03" }), { status: 200 })
      }
      if (url.includes("/api/tasks/active")) {
        return new Response(JSON.stringify([]), { status: 200 })
      }
      if (url.includes("/git/tree")) {
        treeCalls += 1
      }
      return gitResponse(url, init) ?? new Response(JSON.stringify(rows), { status: 200 })
    })
    renderDetail("/projects/2")

    await screen.findByText("acme/Demo")
    await userEvent.click(screen.getByRole("button", { name: "Files" }))
    await screen.findByText("README.md")

    const fileButtons = Array.from(screen.getByRole("tree").querySelectorAll("li button"))
    const readme = fileButtons.find((button) => button.textContent?.includes("README.md"))
    if (readme === undefined) {
      throw new Error("README.md row not found")
    }
    await userEvent.click(readme)
    expect(await screen.findByText("# README.md")).toBeDefined()

    await userEvent.click(screen.getByRole("button", { name: "Sync" }))

    expect(await screen.findByText("Select a file to preview")).toBeDefined()
    expect(screen.queryByText("# README.md")).toBeNull()
    expect(treeCalls).toBeGreaterThan(0)
  })

  it("refreshes the files after a sync", async () => {
    let treeCalls = 0
    stubFetch((url) => {
      if (url.includes("/sync")) {
        return new Response(JSON.stringify({ ...rows[0], status: "READY", lastSyncedAt: "2026-03-03" }), { status: 200 })
      }
      if (url.includes("/api/tasks/active")) {
        return new Response(JSON.stringify([]), { status: 200 })
      }
      if (url.includes("/git/tree")) {
        treeCalls += 1
      }
      return gitResponse(url) ?? new Response(JSON.stringify(rows), { status: 200 })
    })
    renderDetail("/projects/2")

    await screen.findByText("acme/Demo")
    await userEvent.click(screen.getByRole("button", { name: "Files" }))
    await screen.findByText("README.md")

    const before = treeCalls
    await userEvent.click(screen.getByRole("button", { name: "Sync" }))

    await waitFor(() => expect(treeCalls).toBeGreaterThan(before))
  })

  it("keeps the files placeholder for the audits section", async () => {
    stubProjects()
    renderDetail("/projects/2")

    await screen.findByText("acme/Demo")
    await userEvent.click(screen.getByRole("button", { name: "Audits" }))

    expect(await screen.findByText("audits coming in the next HU")).toBeDefined()
    expect(screen.queryByRole("tree")).toBeNull()
  })

  it("applies the selected version from the selectors above the header", async () => {
    stubProjects()
    renderDetail("/projects/2")

    await screen.findByText("acme/Demo")
    expect(await screen.findByText("Branch")).toBeDefined()
    expect(screen.getByText("Commit")).toBeDefined()
    expect(screen.getByLabelText("Search items")).toBeDefined()
    expect(screen.queryByRole("button", { name: "Apply version" })).toBeNull()

    await userEvent.clear(screen.getByLabelText("Search items"))
    await userEvent.type(screen.getByLabelText("Search items"), `${"b".repeat(40)}{enter}`)

    expect(await screen.findByText("Version main at bbbbbbb applied")).toBeDefined()
  })
})
