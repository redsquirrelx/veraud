import { act, render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { createMemoryRouter, RouterProvider } from "react-router-dom"
import { I18nextProvider } from "react-i18next"
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest"
import { router } from "./router.tsx"
import { i18n, initializeI18n } from "../shared/i18n/index.ts"

vi.mock("./useBackendStatus.ts", () => ({ useBackendStatus: () => ({ backend: "online", agent: "offline" }) }))
vi.mock("./dock.tsx", () => ({ Dock: () => <div data-testid="dock" /> }))

const project = { id: 2, repositoryOwner: "acme", repositoryName: "Demo", cloneProtocol: "https", status: "READY", registeredAt: "2026-01-01", lastSyncedAt: null, branch: null, commitHash: null }

function renderRoute(path: string) {
  const memoryRouter = createMemoryRouter(router.routes, { initialEntries: [path] })
  return { ...render(<I18nextProvider i18n={i18n}><RouterProvider router={memoryRouter} /></I18nextProvider>), router: memoryRouter }
}

beforeAll(async () => {
  await initializeI18n("en")
})

beforeEach(() => {
  window.localStorage.clear()
  vi.stubGlobal("WebSocket", class { addEventListener() {} close() {} })
  vi.stubGlobal("fetch", vi.fn(async (input: unknown) => {
    const path = new URL(String(input)).pathname
    let data: unknown = []
    if (path === "/api/projects") data = [project]
    if (path.endsWith("/git/branches")) data = { branches: ["main"], currentBranch: "main", detachedHash: null, taskId: 1 }
    if (path.endsWith("/git/commits")) data = { branch: "main", commits: [{ commitHash: "a".repeat(40), subject: "init" }], limit: 30, offset: 0, taskId: 2 }
    return new Response(JSON.stringify(data), { status: 200 })
  }))
})
afterEach(() => vi.unstubAllGlobals())

describe("project route navigation", () => {
  it("enters from Home, opens sidebar docs, visits Settings and returns with persisted collapse", async () => {
    const user = userEvent.setup()
    const { router: memoryRouter } = renderRoute("/")
    expect(screen.getByRole("banner")).toBeDefined()
    await user.click(await screen.findByRole("button", { name: "Inspect" }))
    await screen.findByRole("heading", { name: "acme/Demo" })
    expect(screen.getByRole("main")).toHaveClass("app-project-layout")
    const sidebar = within(screen.getByRole("complementary", { name: "Project" }))
    expect(sidebar.getByText("Backend: Online")).toBeDefined()
    await user.click(sidebar.getByRole("button", { name: "API docs" }))
    expect(sidebar.getByRole("link", { name: /WebSocket docs/ })).toHaveAttribute("target", "_blank")
    await user.keyboard("{Escape}")
    await user.click(sidebar.getByRole("button", { name: "Collapse sidebar" }))
    await user.click(sidebar.getByRole("link", { name: "Settings" }))
    expect(await screen.findByRole("heading", { name: "Settings" })).toBeDefined()
    expect(screen.getByRole("banner")).toBeDefined()
    await act(async () => { await memoryRouter.navigate(-1) })
    await screen.findByRole("heading", { name: "acme/Demo" })
    expect(screen.getByRole("button", { name: "Expand sidebar" })).toBeDefined()
    expect(screen.getAllByTestId("dock")).toHaveLength(1)
  })

  it("renders direct detail URLs and restores the sidebar after a fresh route mount", async () => {
    const user = userEvent.setup()
    const first = renderRoute("/projects/2")
    await screen.findByRole("heading", { name: "acme/Demo" })
    await user.click(screen.getByRole("button", { name: "Collapse sidebar" }))
    first.unmount()
    first.router.dispose()
    renderRoute("/projects/2")
    await screen.findByRole("heading", { name: "acme/Demo" })
    expect(screen.getByRole("button", { name: "Expand sidebar" })).toBeDefined()
    expect(screen.getByLabelText("Project context")).toBeDefined()
  })

  it("keeps sidebar navigation available while loading and when project loading fails", async () => {
    let release: (response: Response) => void = () => {}
    const normalFetch = vi.mocked(fetch).getMockImplementation()!
    vi.mocked(fetch).mockImplementation((input, init) => new URL(String(input)).pathname === "/api/projects"
      ? new Promise<Response>((resolve) => { release = resolve })
      : normalFetch(input, init))
    renderRoute("/projects/2")
    expect(screen.getByRole("status")).toHaveTextContent("Loading project")
    expect(screen.getByRole("link", { name: "Home" })).toBeDefined()
    await act(async () => { release(new Response("{}", { status: 503 })) })
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load the project")
    expect(screen.getByRole("link", { name: "Settings" })).toBeDefined()
    expect(screen.queryByLabelText("Project context")).toBeNull()
  })

  it("keeps global navigation available for a nonexistent project", async () => {
    renderRoute("/projects/99")
    expect(await screen.findByText("Project not found")).toBeDefined()
    expect(screen.getByRole("link", { name: "Home" })).toBeDefined()
    expect(screen.getByRole("button", { name: "API docs" })).toBeDefined()
    expect(screen.queryByLabelText("Project context")).toBeNull()
  })
})
