import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Navigate, Route, Routes } from "react-router-dom"
import { ProjectDetailPage } from "./ProjectDetailPage.tsx"
import { ToastProvider } from "../../app/toasts.tsx"
import { Dock } from "../../app/dock.tsx"

vi.mock("../../shared/ui-kit/MermaidDiagram.tsx", () => ({
  MermaidDiagram: ({ chart, label }: { chart: string; label: string }) => (
    <div role="img" aria-label={label}>{chart}</div>
  ),
}))

const realFetch = globalThis.fetch
const realWebSocket = globalThis.WebSocket

class FakeSocket {
  addEventListener() {}
  close() {}
}

beforeEach(() => {
  window.localStorage.clear()
})

afterEach(() => {
  globalThis.fetch = realFetch
  globalThis.WebSocket = realWebSocket
})

const rows = [
  { id: 2, repositoryOwner: "acme", repositoryName: "Demo", cloneProtocol: "https", status: "READY", registeredAt: "2026-01-01", lastSyncedAt: "2026-01-02", branch: null, commitHash: null },
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
          <Route path="projects/:id" element={<Navigate to="overview" replace />} />
          <Route path="projects/:id/audits/:auditId" element={<ProjectDetailPage />} />
          <Route path="projects/:id/audits/:auditId/evidence/:invocationId" element={<ProjectDetailPage />} />
          <Route path="projects/:id/:section" element={<ProjectDetailPage />} />
        </Routes>
        <Dock />
      </ToastProvider>
    </MemoryRouter>
  )
}

describe("ProjectDetailPage", () => {
  it("renders historical evidence and findings inside project details without reading the working copy", async () => {
    const auditRequests: string[] = []
    const fileRequests: string[] = []
    const historicalRequests: string[] = []
    stubFetch((url, init) => {
      if (url.includes("/audits") && !url.endsWith("/file")) auditRequests.push(url)
      if (url.endsWith("/audits/41/file")) {
        historicalRequests.push(String(init?.body))
        return new Response(JSON.stringify({ path: "src/service.ts", content: "// audited complete source\nexport const value = 1", size: 55, commitHash: "audited-commit" }), { status: 200 })
      }
      if (url.endsWith("/api/projects/2/file")) fileRequests.push(String(init?.body))
      if (url.endsWith("/audits/41")) return new Response(JSON.stringify({ id: 41, branch: "main", commitHash: "audited-commit", executionStatus: "Completed", reportAvailable: true }), { status: 200 })
      if (url.endsWith("/report/sections/quality_results")) return new Response(JSON.stringify({ section: "quality_results", data: {
        findings: [{ id: "F-1", title: "Recorded responsibility finding", description: "Historical finding details", evidence_ids: ["E-1"] }],
      } }), { status: 200 })
      if (url.endsWith("/report/sections/annexes_and_traceability")) return new Response(JSON.stringify({ section: "annexes_and_traceability", data: {
        executions: [{ invocation_id: "investigator-1", agent_id: "responsibility" }],
        evidence_inventory: [{ id: "E-1", source: "src/service.ts", content: "Existing evidence content", commit: "audited-commit",
          provenance: { invocation_id: "investigator-1", agent_id: "responsibility" } }],
      } }), { status: 200 })
      if (url.includes("/api/tasks/active") || url.includes("/api/agent-settings")) return new Response("[]", { status: 200 })
      return gitResponse(url, init) ?? new Response(JSON.stringify(rows), { status: 200 })
    })
    renderDetail("/projects/2/audits/41/evidence/investigator-1?agent=responsibility&name=Responsibility")
    expect(await screen.findByRole("heading", { name: "Agent evidence" })).toBeVisible()
    expect(screen.getByRole("heading", { name: "acme/Demo" })).toBeVisible()
    expect(await screen.findByText("Responsibility")).toBeVisible()
    expect(screen.getAllByText("investigator-1").length).toBeGreaterThan(0)
    expect(screen.getByRole("button", { name: "Audits" })).toHaveAttribute("aria-current", "page")
    await waitFor(() => expect(screen.getByRole("region", { name: "Read-only code viewer" })).toHaveTextContent("audited complete source"))
    expect(auditRequests).toHaveLength(3)
    expect(auditRequests[0]).toMatch(/\/audits\/41$/)
    expect(auditRequests).toEqual(expect.arrayContaining([expect.stringMatching(/\/report\/sections\/annexes_and_traceability$/), expect.stringMatching(/\/report\/sections\/quality_results$/)]))
    expect(fileRequests).toEqual([])
    expect(historicalRequests).toEqual([JSON.stringify({ path: "src/service.ts" })])
    expect(screen.queryByRole("button", { name: "Use recorded evidence" })).toBeNull()
    expect(screen.getByText("Audited branch")).toBeVisible()
    expect(screen.getByText("Audited commit")).toBeVisible()
    await userEvent.click(await screen.findByRole("button", { name: "F-1 — Recorded responsibility finding" }))
    expect(await screen.findByRole("dialog", { name: "Recorded responsibility finding" })).toHaveTextContent("Historical finding details")
    expect(fileRequests).toEqual([])
  })

  it("embeds configured executed-agent evidence in the audit results tab while keeping the project context", async () => {
    const commit = "a".repeat(40)
    const reads: string[] = []
    stubFetch((url, init) => {
      if (url.endsWith("/audits/41")) return new Response(JSON.stringify({ id: 41, branch: "main", commitHash: commit,
        executionStatus: "Completed", reportAvailable: true, configurationAvailable: true }), { status: 200 })
      if (url.endsWith("/audits/41/configuration")) return new Response(JSON.stringify({ configuration: {
        version: 1, branch: "main", commitHash: commit, attributes: ["maintainability"], scopes: [{ id: "maintainability",
          requiredAgents: [{ id: "responsibility", name: "Saved responsibility investigator" }], subcharacteristics: [], techniques: [], investigators: [] }],
      }, invocations: [{ id: "inv-1", agentId: "responsibility", status: "completed" }] }), { status: 200 })
      if (url.endsWith("/report/sections/annexes_and_traceability")) return new Response(JSON.stringify({ section: "annexes_and_traceability", data: {
        executions: [{ invocation_id: "inv-1", agent_id: "responsibility" }], evidence_inventory: [{ id: "E-embedded", kind: "source", source: "Demo/src/example.ts",
          commit, start_line: 1, end_line: 1, provenance: { invocation_id: "inv-1", agent_id: "responsibility" } }],
      } }), { status: 200 })
      if (url.endsWith("/report/sections/quality_results")) return new Response(JSON.stringify({ section: "quality_results", data: { findings: [
        { id: "F-navigation", title: "Evidence navigation finding", evidence_ids: ["E-embedded"] },
      ] } }), { status: 200 })
      if (url.endsWith("/report/sections/executive_summary")) return new Response(JSON.stringify({ section: "executive_summary", data: {} }), { status: 200 })
      if (url.endsWith("/audits/41/file")) {
        reads.push(String(init?.body))
        return new Response(JSON.stringify({ path: "src/example.ts", content: "export const audited = true", size: 27, commitHash: commit }), { status: 200 })
      }
      if (url.includes("/api/tasks/active") || url.includes("/api/agent-settings")) return new Response("[]", { status: 200 })
      return gitResponse(url, init) ?? new Response(JSON.stringify(rows), { status: 200 })
    })
    renderDetail("/projects/2/audits/41")
    expect(await screen.findByRole("heading", { name: "Audit report · #41" })).toBeVisible()
    await userEvent.click(screen.getByRole("tab", { name: "Evidence" }))
    await userEvent.selectOptions(await screen.findByRole("combobox", { name: "Executed agent" }), "responsibility")
    expect(await screen.findByText("E-embedded")).toBeVisible()
    await waitFor(() => expect(screen.getByRole("region", { name: "Read-only code viewer" })).toHaveTextContent("export const audited = true"))
    expect(screen.getByRole("tab", { name: "Evidence" })).toHaveAttribute("aria-selected", "true")
    expect(screen.getByRole("button", { name: "Audits" })).toHaveAttribute("aria-current", "page")
    expect(screen.getByRole("heading", { name: "acme/Demo" })).toBeVisible()
    expect(reads).toEqual([JSON.stringify({ path: "src/example.ts" })])
    await userEvent.click(screen.getByRole("tab", { name: "Findings" }))
    await userEvent.click(await screen.findByRole("button", { name: "Evidence navigation finding" }))
    await userEvent.click(screen.getByRole("link", { name: "View evidence E-embedded" }))
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    expect(screen.getByRole("tab", { name: "Evidence" })).toHaveAttribute("aria-selected", "true")
    expect(screen.getByRole("button", { name: /^E-embedded/ })).toHaveAttribute("aria-pressed", "true")
    expect(reads).toHaveLength(1)
  })

  it("keeps the contextual header and version selection mounted across project sections", async () => {
    stubProjects()
    renderDetail("/projects/2")
    await screen.findByRole("heading", { name: "acme/Demo" })
    const header = screen.getByLabelText("Project context")
    const controls = within(header)
    expect(controls.getByText("READY")).toBeDefined()
    expect(controls.getByText("HTTPS")).toBeDefined()
    await waitFor(() => expect(controls.getByRole("button", { name: "Analyze" })).toBeEnabled())
    const branch = controls.getByRole("button", { name: "main" })
    for (const section of ["Audits", "Files", "Overview"]) {
      await userEvent.click(screen.getByRole("button", { name: section }))
      expect(screen.getByLabelText("Project context")).toBe(header)
      expect(controls.getByRole("button", { name: "main" })).toBe(branch)
      expect(controls.getByRole("button", { name: "Analyze" })).toBeEnabled()
      expect(controls.getByRole("button", { name: "Sync" })).toBeEnabled()
      if (section === "Overview") {
        expect(screen.getByRole("region", { name: "Project overview" })).toBeDefined()
        expect(screen.getByRole("link", { name: "Open on GitHub" })).toBeDefined()
      } else {
        expect(screen.queryByRole("region", { name: "Project overview" })).toBeNull()
        expect(screen.queryByRole("link", { name: "Open on GitHub" })).toBeNull()
        expect(screen.queryByText(/Last synced/)).toBeNull()
      }
    }
  })

  it("shows the project header with sidebar", async () => {
    stubProjects()
    renderDetail("/projects/2")

    expect(await screen.findByText("acme/Demo")).toBeDefined()
    expect(screen.getByText("READY")).toBeDefined()
    expect(screen.getByText("HTTPS")).toBeDefined()
    expect(screen.getByText("Project")).toBeDefined()
    expect(screen.getByText(`Last synced ${new Date("2026-01-02").toLocaleDateString()}`)).toBeDefined()
    expect(screen.getByRole("button", { name: "Sync" })).toBeDefined()

    const link = screen.getByRole("link", { name: "Open on GitHub" })
    expect(link.getAttribute("href")).toBe("https://github.com/acme/Demo")
    expect(link.getAttribute("target")).toBe("_blank")
    expect(link.getAttribute("rel")).toContain("noreferrer")
    expect(link).toHaveClass("ui-button", "ui-button-secondary")
  })

  it("shows SSH for a repository registered over SSH", async () => {
    stubFetch((url, init) => {
      if (url.includes("/api/tasks/active")) {
        return new Response(JSON.stringify([]), { status: 200 })
      }
      return gitResponse(url, init) ?? new Response(JSON.stringify([{ ...rows[0], cloneProtocol: "ssh" }]), { status: 200 })
    })
    renderDetail("/projects/2")

    expect(await screen.findByText("SSH")).toBeDefined()
    expect(screen.queryByText("HTTPS")).toBeNull()
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

  it("shows quality audit status and its configuration entry independently of the file tree", async () => {
    stubProjects()
    renderDetail("/projects/2")

    await screen.findByText("acme/Demo")
    await userEvent.click(screen.getByRole("button", { name: "Audits" }))

    expect(await screen.findByRole("heading", { name: "Quality audit" })).toBeDefined()
    expect(screen.getByRole("region", { name: "Maintainability" })).toHaveTextContent("Enabled")
    expect(screen.queryByRole("checkbox", { name: "Maintainability" })).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Configure audit" })).toBeInTheDocument()
    expect(screen.queryByRole("tree")).toBeNull()
  })

  it("opens quality audits directly from the header Analyze button without starting an execution", async () => {
    const executions: string[] = []
    stubFetch((url, init) => {
      if (init?.method === "POST" && (url.includes("/audits") || url.includes("/agent-executions"))) executions.push(url)
      if (url.includes("/api/tasks/active") || url.includes("/api/agent-settings") || url.endsWith("/api/projects/2/audits")) {
        return new Response("[]", { status: 200 })
      }
      return gitResponse(url, init) ?? new Response(JSON.stringify(rows), { status: 200 })
    })
    renderDetail("/projects/2")
    const analyze = await screen.findByRole("button", { name: "Analyze" })
    expect(analyze).not.toHaveAttribute("aria-haspopup")
    await userEvent.click(analyze)
    expect(await screen.findByRole("heading", { name: "Quality audit" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Configure audit" })).toBeInTheDocument()
    expect(screen.queryByRole("menu")).not.toBeInTheDocument()
    expect(executions).toEqual([])
  })

  it.each([false, true])("opens dedicated audit results and keeps the Audits sidebar selected (direct: %s)", async (direct) => {
    const audit = { id: 8, evaluationId: 4, runId: "original-run", branch: "report-branch", commitHash: "b".repeat(40), attributes: ["maintainability"],
      executionStatus: "Completed", auditStatus: "partial", error: null, createdAt: "2026-10-17T10:00:00Z", finishedAt: null, reportAvailable: true }
    const requested: string[] = []
    stubFetch((url, init) => {
      requested.push(url)
      if (url.includes("/api/tasks/active") || url.includes("/api/agent-settings")) return new Response("[]", { status: 200 })
      if (url.endsWith("/api/projects/2/audits")) return new Response(JSON.stringify([audit]), { status: 200 })
      if (url.endsWith("/api/projects/2/audits/8")) return new Response(JSON.stringify(audit), { status: 200 })
      if (url.endsWith("/api/projects/2/audits/8/report/sections/executive_summary")) return new Response(JSON.stringify({
        section: "executive_summary", data: { conclusion: "Saved audit result" },
      }), { status: 200 })
      return gitResponse(url, init) ?? new Response(JSON.stringify(rows), { status: 200 })
    })
    renderDetail(direct ? "/projects/2/audits/8" : "/projects/2/audits")
    if (!direct) await userEvent.click(await screen.findByRole("link", { name: "View results" }))
    expect(await screen.findByRole("heading", { name: "Audit results · #8" })).toBeInTheDocument()
    expect(await screen.findByText("Saved audit result")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Audits" })).toHaveAttribute("aria-current", "page")
    expect(screen.queryByRole("heading", { name: "Project audits" })).not.toBeInTheDocument()
    const resultsHeader = within(screen.getByLabelText("Audit details"))
    expect(resultsHeader.getByText("acme/Demo")).toBeInTheDocument()
    expect(resultsHeader.getByText("report-branch")).toBeInTheDocument()
    expect(resultsHeader.getByText("b".repeat(40))).toBeInTheDocument()
    expect(requested.some((url) => url.endsWith("/audits/8/report"))).toBe(false)
    if (direct) expect(requested.some((url) => url.endsWith("/api/projects/2/audits"))).toBe(false)
    await userEvent.click(screen.getByRole("link", { name: "Back to audits" }))
    expect(await screen.findByRole("heading", { name: "Project audits" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Audits" })).toHaveAttribute("aria-current", "page")
  })

  it("applies the selected version from the selectors above the header", async () => {
    stubProjects()
    renderDetail("/projects/2")

    await screen.findByText("acme/Demo")
    expect(await screen.findByText("Branch")).toBeDefined()
    expect(screen.getByText("Commit")).toBeDefined()
    expect(screen.queryByRole("button", { name: "Apply version" })).toBeNull()

    await waitFor(() => {
      expect(screen.getByLabelText("Search items")).toHaveValue("aaaaaaa")
      expect(screen.getByLabelText("Search items")).not.toBeDisabled()
    })
    await userEvent.clear(screen.getByLabelText("Search items"))
    await userEvent.type(screen.getByLabelText("Search items"), `${"b".repeat(40)}{enter}`)

    expect(await screen.findByText("Version main at bbbbbbb applied")).toBeDefined()
  })

  it("analyzes the applied version and shows the run in audits", async () => {
    const seen: Array<{ url: string, body: unknown }> = []
    const waiting = (id: number, agentType: string, configuration: unknown = null) => ({
      id,
      evaluationId: 7,
      agentType,
      configuration,
      status: "Waiting",
      result: null,
      error: null,
      inputTokens: null,
      outputTokens: null,
      createdAt: "2026-01-01",
      startedAt: null,
      finishedAt: null,
    })
    const captured = {
      model: { id: 1, name: "captured-model", providerId: 1, providerName: "OpenAI" },
      credential: { id: 2, name: "captured-credential", providerId: 1, providerName: "OpenAI" },
      temperature: 0.2, maxTokens: 2048,
    }
    stubFetch((url, init) => {
      if (url.includes("/api/tasks/active")) {
        return new Response(JSON.stringify([]), { status: 200 })
      }
      if (url.endsWith("/architecture")) {
        seen.push({ url, body: JSON.parse(String(init?.body ?? "{}")) as unknown })
        return new Response(JSON.stringify({
          versionId: 9,
          evaluationId: 7,
          executions: {
            orientation: waiting(21, "orientation"),
            architecture: waiting(22, "architecture"),
            semantic_validation: { ...waiting(23, "semantic_validation"), configuration: captured },
          },
        }), { status: 201 })
      }
      return gitResponse(url, init) ?? new Response(JSON.stringify(rows), { status: 200 })
    })
    renderDetail("/projects/2")

    await screen.findByText("acme/Demo")
    const analyze = await screen.findByRole("button", { name: "Analyze" })
    await waitFor(() => expect(analyze.hasAttribute("disabled")).toBe(false))
    await userEvent.click(analyze)
    await userEvent.click(await screen.findByRole("menuitem", { name: /Project architecture/ }))

    expect(seen.length).toBe(1)
    expect(seen[0]?.url).toContain("/api/projects/2/architecture")
    expect(seen[0]?.body).toEqual({ branch: "main", commitHash: "a".repeat(40) })

    // The run shows in the header card spinner.
    expect(await screen.findByText("Analyzing the project")).toBeDefined()

    // Sync stays disabled while the pipeline reads the checkout.
    expect(screen.getByRole("button", { name: "Sync" }).hasAttribute("disabled")).toBe(true)

    await userEvent.click(screen.getByRole("button", { name: "Audits" }))

    // The semantic_validation row finishes last, so it is the tracked run.
    expect(await screen.findByText("semantic_validation run #23")).toBeDefined()
    expect(screen.getAllByText("Waiting")).toHaveLength(3)
    expect(screen.getByRole("heading", { name: "Configuration used" })).toBeDefined()
    expect(screen.getByText("captured-model")).toBeDefined()
    expect(screen.getByText("captured-credential (#2)")).toBeDefined()
  })

  it("starts the project-architecture pipeline from the Analyze menu tracking validation", async () => {
    const seen: Array<{ url: string, body: unknown }> = []
    const waiting = (id: number, agentType: string) => ({
      id,
      evaluationId: 7,
      agentType,
      status: "Waiting",
      result: null,
      error: null,
      inputTokens: null,
      outputTokens: null,
      createdAt: "2026-01-01",
      startedAt: null,
      finishedAt: null,
    })
    stubFetch((url, init) => {
      if (url.includes("/api/tasks/active")) {
        return new Response(JSON.stringify([]), { status: 200 })
      }
      if (url.endsWith("/architecture")) {
        seen.push({ url, body: JSON.parse(String(init?.body ?? "{}")) as unknown })
        return new Response(JSON.stringify({
          versionId: 9,
          evaluationId: 7,
          executions: {
            orientation: waiting(21, "orientation"),
            architecture: waiting(22, "architecture"),
            semantic_validation: waiting(23, "semantic_validation"),
          },
        }), { status: 201 })
      }
      return gitResponse(url, init) ?? new Response(JSON.stringify(rows), { status: 200 })
    })
    renderDetail("/projects/2")

    await screen.findByText("acme/Demo")
    const analyze = await screen.findByRole("button", { name: "Analyze" })
    await waitFor(() => expect(analyze.hasAttribute("disabled")).toBe(false))
    await userEvent.click(analyze)
    await userEvent.click(await screen.findByRole("menuitem", { name: /Project architecture/ }))

    expect(seen.length).toBe(1)
    expect(seen[0]?.url).toContain("/api/projects/2/architecture")
    expect(seen[0]?.body).toEqual({ branch: "main", commitHash: "a".repeat(40) })

    await userEvent.click(screen.getByRole("button", { name: "Audits" }))

    // The semantic_validation row finishes last, so it is the tracked run.
    expect(await screen.findByText("semantic_validation run #23")).toBeDefined()
    expect(screen.getAllByText("Waiting")).toHaveLength(3)
  })

  it("renders parsed orientation content once its run completes", async () => {    const orientationResult = JSON.stringify({
      completion_status: "complete",
      orientation: {
        project_type: { statement: "A command-line tool.", status: "supported", evidence_ids: ["e1"] },
        purpose: null,
        components: [],
        starting_points: [],
        uncertainties: [],
      },
    })
    const waiting = (id: number, agentType: string) => ({
      id,
      evaluationId: 7,
      agentType,
      status: "Waiting",
      result: null,
      error: null,
      inputTokens: null,
      outputTokens: null,
      createdAt: "2026-01-01",
      startedAt: null,
      finishedAt: null,
    })
    const completedOrientation = {
      ...waiting(21, "orientation"),
      status: "Completed",
      result: orientationResult,
      startedAt: "2026-01-01",
      finishedAt: "2026-01-01",
    }
    stubFetch((url, init) => {
      if (url.includes("/api/tasks/active")) {
        return new Response(JSON.stringify([]), { status: 200 })
      }
      if (url.endsWith("/architecture")) {
        return new Response(JSON.stringify({
          versionId: 9,
          evaluationId: 7,
          executions: {
            orientation: completedOrientation,
            architecture: waiting(22, "architecture"),
            semantic_validation: waiting(23, "semantic_validation"),
          },
        }), { status: 201 })
      }
      if (url.includes("/api/projects/2/versions")) {
        return new Response(JSON.stringify([{
          id: 9,
          branch: "main",
          commitHash: "a".repeat(40),
          analysisStatus: "Pending",
          analyzedAt: null,
          evaluationId: 7,
          execution: completedOrientation,
          executions: [completedOrientation, waiting(22, "architecture"), waiting(23, "semantic_validation")],
          derivedStatus: "Waiting",
        }]), { status: 200 })
      }
      if (url.includes("/agent-executions/23")) {
        return new Response(JSON.stringify(waiting(23, "semantic_validation")), { status: 200 })
      }
      return gitResponse(url, init) ?? new Response(JSON.stringify(rows), { status: 200 })
    })
    // A previous test may have left a tracked run behind; start clean so the
    // menu is enabled and nothing restores mid-test.
    window.localStorage.removeItem("analysis.lastExecution.2")
    // Open the analysis section directly: result cards render there.
    renderDetail("/projects/2/analysis")

    await screen.findByText("acme/Demo")
    const analyze = await screen.findByRole("button", { name: "Analyze" })
    await waitFor(() => expect(analyze.hasAttribute("disabled")).toBe(false))
    await userEvent.click(analyze)
    await userEvent.click(await screen.findByRole("menuitem", { name: /Project architecture/ }))

    expect(await screen.findByText("orientation run #21")).toBeDefined()
    expect(await screen.findByText("Orientation")).toBeDefined()
    expect(await screen.findByText("A command-line tool.")).toBeDefined()
  })

  it("explains a failed architecture run with its issues", async () => {
    const failedArchitecture = JSON.stringify({
      completion_status: "failed",
      architecture: null,
      limitations: ["Snapshot capped."],
      execution_issues: [{ id: "issue:1", stage: "architecture", category: "call_limit", message: "Model-call limit reached." }],
    })
    const completed = (id: number, agentType: string, result: string | null) => ({
      id,
      evaluationId: 7,
      agentType,
      status: "Completed",
      result,
      error: null,
      inputTokens: null,
      outputTokens: null,
      createdAt: "2026-01-01",
      startedAt: "2026-01-01",
      finishedAt: "2026-01-01",
    })
    stubFetch((url, init) => {
      if (url.includes("/api/tasks/active")) {
        return new Response(JSON.stringify([]), { status: 200 })
      }
      if (url.endsWith("/architecture")) {
        return new Response(JSON.stringify({
          versionId: 9,
          evaluationId: 7,
          executions: {
            orientation: completed(21, "orientation", null),
            architecture: completed(22, "architecture", failedArchitecture),
            semantic_validation: completed(23, "semantic_validation", null),
          },
        }), { status: 201 })
      }
      if (url.includes("/api/projects/2/versions")) {
        return new Response(JSON.stringify([]), { status: 200 })
      }
      return gitResponse(url, init) ?? new Response(JSON.stringify(rows), { status: 200 })
    })
    window.localStorage.removeItem("analysis.lastExecution.2")
    renderDetail("/projects/2/analysis")

    await screen.findByText("acme/Demo")
    const analyze = await screen.findByRole("button", { name: "Analyze" })
    await waitFor(() => expect(analyze.hasAttribute("disabled")).toBe(false))
    await userEvent.click(analyze)
    await userEvent.click(await screen.findByRole("menuitem", { name: /Project architecture/ }))

    expect(await screen.findByText("call_limit")).toBeDefined()
    expect(await screen.findByText("Model-call limit reached.", { exact: false })).toBeDefined()
    expect(await screen.findByText("Snapshot capped.")).toBeDefined()
  })

  it("disables Analyze while a sync is running", async () => {
    stubFetch((url, init) => {
      if (url.includes("/api/tasks/active")) {
        return new Response(JSON.stringify([]), { status: 200 })
      }
      if (url.endsWith("/sync")) {
        // The sync never settles: the button must stay off meanwhile.
        return new Promise<Response>(() => {})
      }
      return gitResponse(url, init) ?? new Response(JSON.stringify(rows), { status: 200 })
    })
    renderDetail("/projects/2")

    await screen.findByText("acme/Demo")
    const analyze = await screen.findByRole("button", { name: "Analyze" })
    await waitFor(() => expect(analyze.hasAttribute("disabled")).toBe(false))

    await userEvent.click(screen.getByRole("button", { name: "Sync" }))

    await waitFor(() => expect(screen.getByRole("button", { name: "Analyze" }).hasAttribute("disabled")).toBe(true))
  })

  it("checks out an analyzed version and shows its stored run", async () => {
    const completed = {
      id: 21,
      evaluationId: 7,
      agentType: "analyzer",
      status: "Completed",
      result: "{\"kind\":\"library\"}",
      error: null,
      inputTokens: null,
      outputTokens: null,
      createdAt: "2026-01-01",
      startedAt: "2026-01-01",
      finishedAt: "2026-01-01",
    }
    const architectCompleted = { ...completed, id: 31, agentType: "architect", result: "{\"style\":\"layered\"}" }
    const waitingRun = { ...completed, id: 22, status: "Waiting", result: null, finishedAt: null }
    const versions = [
      { id: 9, branch: "main", commitHash: "b".repeat(40), analysisStatus: "Pending", analyzedAt: null, evaluationId: 7, executions: [completed, architectCompleted], derivedStatus: "Completed" },
      { id: 10, branch: "main", commitHash: "c".repeat(40), analysisStatus: "Pending", analyzedAt: null, evaluationId: 8, executions: [waitingRun], derivedStatus: "Waiting" },
    ]
    const seen: string[] = []
    stubFetch((url, init) => {
      if (url.includes("/api/tasks/active")) {
        return new Response(JSON.stringify([]), { status: 200 })
      }
      if (url.endsWith("/versions")) {
        return new Response(JSON.stringify(versions), { status: 200 })
      }
      if (url.includes("/agent-executions/22")) {
        return new Response(JSON.stringify(waitingRun), { status: 200 })
      }
      if (url.includes("/agent-executions/")) {
        return new Response(JSON.stringify({ message: "Agent execution not found" }), { status: 404 })
      }
      if (url.includes("/git/checkout") && !url.includes("checkout-branch")) {
        seen.push(String(init?.body ?? ""))
      }
      return gitResponse(url, init) ?? new Response(JSON.stringify(rows), { status: 200 })
    })
    renderDetail("/projects/2")

    await screen.findByText("acme/Demo")
    await userEvent.click(screen.getByRole("tab", { name: /Analyzed/ }))
    await userEvent.click(screen.getByRole("button", { name: "Select an analyzed version" }))
    await userEvent.click(screen.getByRole("option", { name: "main @ bbbbbbb · Completed" }))

    expect(await screen.findByText(`(HEAD detached at ${"b".repeat(40)}) - select a branch to re-attach`)).toBeDefined()
    expect(seen[0]).toContain("b".repeat(40))

    await userEvent.click(screen.getByRole("button", { name: "Audits" }))

    // The architect carries the final verdict, so a version with both rows
    // shows the architect run.
    expect(await screen.findByText("architect run #31")).toBeDefined()
    expect(screen.getAllByText("Completed").length).toBe(2)

    // A second pick moves the detached checkout without re-attaching first.
    await userEvent.click(screen.getByRole("button", { name: "Overview" }))
    await userEvent.click(screen.getByRole("tab", { name: /Analyzed/ }))
    await userEvent.click(screen.getByRole("button", { name: "main @ bbbbbbb · Completed" }))
    await userEvent.click(screen.getByRole("option", { name: "main @ ccccccc · Waiting" }))

    expect(await screen.findByText(`(HEAD detached at ${"c".repeat(40)}) - select a branch to re-attach`)).toBeDefined()
    expect(seen[1]).toContain("c".repeat(40))

    await userEvent.click(screen.getByRole("button", { name: "Audits" }))

    // A version with only the analyzer row falls back to it.
    expect(await screen.findByText("analyzer run #22")).toBeDefined()
  })

  it("does not toast when showing a stored analysis", async () => {
    const completed = {
      id: 21,
      evaluationId: 7,
      agentType: "analyzer",
      status: "Completed",
      result: "{\"kind\":\"library\"}",
      error: null,
      inputTokens: null,
      outputTokens: null,
      createdAt: "2026-01-01",
      startedAt: "2026-01-01",
      finishedAt: "2026-01-01",
    }
    stubFetch((url, init) => {
      if (url.includes("/api/tasks/active")) {
        return new Response(JSON.stringify([]), { status: 200 })
      }
      if (url.endsWith("/versions")) {
        return new Response(JSON.stringify([
          { id: 9, branch: "main", commitHash: "b".repeat(40), analysisStatus: "Pending", analyzedAt: null, evaluationId: 7, executions: [completed], derivedStatus: "Completed" },
        ]), { status: 200 })
      }
      if (url.includes("/agent-executions/")) {
        return new Response(JSON.stringify({ message: "Agent execution not found" }), { status: 404 })
      }
      return gitResponse(url, init) ?? new Response(JSON.stringify(rows), { status: 200 })
    })
    renderDetail("/projects/2")

    await screen.findByText("acme/Demo")
    await userEvent.click(screen.getByRole("tab", { name: /Analyzed/ }))
    await userEvent.click(screen.getByRole("button", { name: "Select an analyzed version" }))
    await userEvent.click(screen.getByRole("option", { name: "main @ bbbbbbb · Completed" }))

    await userEvent.click(screen.getByRole("button", { name: "Audits" }))

    expect(await screen.findByText("analyzer run #21")).toBeDefined()
    expect(screen.queryByText("Analysis completed")).toBeNull()
  })

  it("shows the analysis verdict in Overview", async () => {
    const completed = {
      id: 21,
      evaluationId: 7,
      agentType: "orientation",
      status: "Completed",
      result: "{\"completion_status\":\"complete\",\"orientation\":{\"project_type\":{\"statement\":\"A command-line tool.\",\"status\":\"supported\",\"evidence_ids\":[\"e1\"]},\"purpose\":null,\"components\":[],\"starting_points\":[],\"uncertainties\":[]}}",
      error: null,
      inputTokens: null,
      outputTokens: null,
      createdAt: "2026-01-01",
      startedAt: "2026-01-01",
      finishedAt: "2026-01-01",
    }
    stubFetch((url, init) => {
      if (url.includes("/api/tasks/active")) {
        return new Response(JSON.stringify([]), { status: 200 })
      }
      if (url.endsWith("/versions")) {
        return new Response(JSON.stringify([
          { id: 9, branch: "main", commitHash: "b".repeat(40), analysisStatus: "Pending", analyzedAt: null, evaluationId: 7, executions: [completed], derivedStatus: "Completed" },
        ]), { status: 200 })
      }
      if (url.includes("/agent-executions/")) {
        return new Response(JSON.stringify({ message: "Agent execution not found" }), { status: 404 })
      }
      return gitResponse(url, init) ?? new Response(JSON.stringify(rows), { status: 200 })
    })
    renderDetail("/projects/2")

    await screen.findByText("acme/Demo")
    await userEvent.click(screen.getByRole("tab", { name: /Analyzed/ }))
    await userEvent.click(screen.getByRole("button", { name: "Select an analyzed version" }))
    await userEvent.click(screen.getByRole("option", { name: "main @ bbbbbbb · Completed" }))

    expect(await screen.findByText("acme/Demo")).toBeDefined()
    // The Overview summary card shows the orientation verdict.
    expect(await screen.findByText("Summary")).toBeDefined()
    expect(screen.getByText("Project type")).toBeDefined()
    expect(screen.getByText("A command-line tool.")).toBeDefined()
    expect(screen.queryByText("Analyzing")).toBeNull()

    await userEvent.click(screen.getByRole("button", { name: "Audits" }))

    expect(await screen.findByText("orientation run #21")).toBeDefined()
  })

  it("shows an Analyzing badge while the run is open", async () => {
    const waiting = (id: number, agentType: string) => ({
      id,
      evaluationId: 7,
      agentType,
      status: "Waiting",
      result: null,
      error: null,
      inputTokens: null,
      outputTokens: null,
      createdAt: "2026-01-01",
      startedAt: null,
      finishedAt: null,
    })
    stubFetch((url, init) => {
      if (url.includes("/api/tasks/active")) {
        return new Response(JSON.stringify([]), { status: 200 })
      }
      if (url.endsWith("/architecture")) {
        return new Response(JSON.stringify({
          versionId: 9,
          evaluationId: 7,
          executions: {
            orientation: waiting(21, "orientation"),
            architecture: waiting(22, "architecture"),
            semantic_validation: waiting(23, "semantic_validation"),
          },
        }), { status: 201 })
      }
      if (url.includes("/agent-executions/")) {
        return new Response(JSON.stringify({ message: "Agent execution not found" }), { status: 404 })
      }
      return gitResponse(url, init) ?? new Response(JSON.stringify(rows), { status: 200 })
    })
    renderDetail("/projects/2")

    await screen.findByText("acme/Demo")
    const analyze = await screen.findByRole("button", { name: "Analyze" })
    await waitFor(() => expect(analyze.hasAttribute("disabled")).toBe(false))
    await userEvent.click(analyze)
    await userEvent.click(await screen.findByRole("menuitem", { name: /Project architecture/ }))

    const headerRow = screen.getByRole("heading", { name: "acme/Demo" }).parentElement
    if (headerRow === null) {
      throw new Error("project header row not found")
    }
    expect(within(headerRow as HTMLElement).getByText("Analyzing")).toBeDefined()
    expect(screen.queryByText("library")).toBeNull()
  })

  it("shows the pipeline summary in overview with a button to the analysis", async () => {
    const base = {
      evaluationId: 7,
      status: "Completed",
      error: null,
      inputTokens: null,
      outputTokens: null,
      createdAt: "2026-01-01",
      startedAt: "2026-01-01",
      finishedAt: "2026-01-01",
    }
    const orientation = {
      ...base,
      id: 21,
      agentType: "orientation",
      result: "{\"completion_status\":\"complete\",\"orientation\":{\"project_type\":{\"statement\":\"A command-line tool.\",\"status\":\"supported\",\"evidence_ids\":[\"e1\"]},\"purpose\":null,\"components\":[],\"starting_points\":[],\"uncertainties\":[]}}",
    }
    const architecture = {
      ...base,
      id: 22,
      agentType: "architecture",
      result: "{\"completion_status\":\"complete\",\"architecture\":{\"organization\":[],\"connections\":[],\"closest_architecture\":{\"pattern\":\"layered\",\"assessment\":{\"statement\":\"Layers are visible.\",\"status\":\"supported\",\"evidence_ids\":[\"e1\"]}},\"deviations\":[],\"infrastructure\":[],\"uncertainties\":[]}}",
    }
    const validation = {
      ...base,
      id: 23,
      agentType: "semantic_validation",
      result: "{\"completion_status\":\"complete\",\"verdict\":\"accepted\",\"selected_target_ids\":[],\"pending_target_ids\":[],\"findings\":[]}",
    }
    stubFetch((url, init) => {
      if (url.includes("/api/tasks/active")) {
        return new Response(JSON.stringify([]), { status: 200 })
      }
      if (url.endsWith("/versions")) {
        return new Response(JSON.stringify([
          { id: 9, branch: "main", commitHash: "b".repeat(40), analysisStatus: "Pending", analyzedAt: null, evaluationId: 7, executions: [orientation, architecture, validation], derivedStatus: "Completed" },
        ]), { status: 200 })
      }
      if (url.includes("/agent-executions/")) {
        return new Response(JSON.stringify({ message: "Agent execution not found" }), { status: 404 })
      }
      return gitResponse(url, init) ?? new Response(JSON.stringify(rows), { status: 200 })
    })
    renderDetail("/projects/2")

    await screen.findByText("acme/Demo")
    await userEvent.click(screen.getByRole("tab", { name: /Analyzed/ }))
    await userEvent.click(screen.getByRole("button", { name: "Select an analyzed version" }))
    await userEvent.click(screen.getByRole("option", { name: "main @ bbbbbbb · Completed" }))

    // Header carries every stage verdict (and the Overview summary repeats them).
    expect(await screen.findByText("A command-line tool.")).toBeDefined()

    // The Overview summary shows key details without the full listing.
    expect(await screen.findByText("Summary")).toBeDefined()
    expect(screen.getByText("layered")).toBeDefined()
    expect(screen.getByText("accepted")).toBeDefined()

    // The button navigates to the analysis subpage without a reload.
    await userEvent.click(screen.getByRole("button", { name: "View full analysis" }))

    expect(await screen.findByRole("heading", { name: "Orientation" })).toBeDefined()
    expect(screen.getByRole("heading", { name: "Architecture" })).toBeDefined()
    expect(screen.getByRole("heading", { name: "Semantic validation" })).toBeDefined()
    expect(screen.getByText("orientation run #21")).toBeDefined()
    expect(screen.getByText("architecture run #22")).toBeDefined()
    expect(screen.getByText("semantic_validation run #23")).toBeDefined()
    expect(screen.queryByText("Summary")).toBeNull()
  })

  it("renders the full analysis at the analysis subpage", async () => {
    const base = {
      evaluationId: 7,
      status: "Completed",
      error: null,
      inputTokens: null,
      outputTokens: null,
      createdAt: "2026-01-01",
      startedAt: "2026-01-01",
      finishedAt: "2026-01-01",
    }
    const orientation = {
      ...base,
      id: 21,
      agentType: "orientation",
      result: "{\"completion_status\":\"complete\",\"orientation\":{\"project_type\":{\"statement\":\"A command-line tool.\",\"status\":\"supported\",\"evidence_ids\":[\"e1\"]},\"purpose\":null,\"components\":[{\"name\":\"core\",\"file_ids\":[\"f1\"],\"responsibility\":{\"statement\":\"Runs the audit.\",\"status\":\"supported\",\"evidence_ids\":[\"e1\"]}}],\"starting_points\":[],\"uncertainties\":[]}}",
    }
    const architecture = {
      ...base,
      id: 22,
      agentType: "architecture",
      result: "{\"completion_status\":\"complete\",\"architecture\":{\"organization\":[{\"name\":\"core\",\"file_ids\":[\"f1\"],\"responsibility\":{\"statement\":\"Holds the core logic.\",\"status\":\"supported\",\"evidence_ids\":[\"e1\"]}}],\"connections\":[],\"closest_architecture\":null,\"deviations\":[],\"infrastructure\":[],\"uncertainties\":[]}}",
    }
    const validation = {
      ...base,
      id: 23,
      agentType: "semantic_validation",
      result: "{\"completion_status\":\"complete\",\"verdict\":\"accepted\",\"selected_target_ids\":[],\"pending_target_ids\":[],\"findings\":[]}",
    }
    stubFetch((url, init) => {
      if (url.includes("/api/tasks/active")) {
        return new Response(JSON.stringify([]), { status: 200 })
      }
      if (url.endsWith("/versions")) {
        return new Response(JSON.stringify([
          { id: 9, branch: "main", commitHash: "b".repeat(40), analysisStatus: "Pending", analyzedAt: null, evaluationId: 7, executions: [orientation, architecture, validation], derivedStatus: "Completed" },
        ]), { status: 200 })
      }
      if (url.includes("/agent-executions/")) {
        return new Response(JSON.stringify({ message: "Agent execution not found" }), { status: 404 })
      }
      return gitResponse(url, init) ?? new Response(JSON.stringify(rows), { status: 200 })
    })
    renderDetail("/projects/2/analysis")

    await screen.findByText("acme/Demo")
    await userEvent.click(screen.getByRole("tab", { name: /Analyzed/ }))
    await userEvent.click(screen.getByRole("button", { name: "Select an analyzed version" }))
    await userEvent.click(screen.getByRole("option", { name: "main @ bbbbbbb · Completed" }))

    // All three runs, each result in its own card.
    expect(await screen.findByText("orientation run #21")).toBeDefined()
    expect(screen.getByText("architecture run #22")).toBeDefined()
    expect(screen.getByText("semantic_validation run #23")).toBeDefined()
    const orientationCard = screen.getByRole("heading", { name: "Orientation" }).closest(".ui-card")
    const architectureCard = screen.getByRole("heading", { name: "Architecture" }).closest(".ui-card")
    const validationCard = screen.getByRole("heading", { name: "Semantic validation" }).closest(".ui-card")
    expect(orientationCard).not.toBeNull()
    expect(architectureCard).not.toBeNull()
    expect(validationCard).not.toBeNull()
    expect(orientationCard).not.toBe(architectureCard)
    expect(architectureCard).not.toBe(validationCard)
    // Orientation sections are shown once in the analysis view.
    expect(screen.getAllByText("A command-line tool.").length).toBe(1)
    expect(screen.getByText("Holds the core logic.", { exact: false })).toBeDefined()
    // The summary card belongs to Overview, not to the analysis subpage.
    expect(screen.queryByText("Summary")).toBeNull()
  })

  it("redirects unknown sections to overview", async () => {
    stubProjects()
    renderDetail("/projects/2/nope")

    expect(await screen.findByText("acme/Demo")).toBeDefined()
    expect(screen.queryByText("Select a file to preview")).toBeNull()
    expect(screen.queryByText("No analysis yet — pick a version and press Analyze")).toBeNull()
  })
})
