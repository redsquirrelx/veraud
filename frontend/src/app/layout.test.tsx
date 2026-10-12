import { beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { Link, MemoryRouter, Route, Routes, useOutletContext } from "react-router-dom"
import { AppLayout, type AppLayoutContext } from "./layout.tsx"
import { StandardLayout } from "./StandardLayout.tsx"
import { ProjectLayout } from "./ProjectLayout.tsx"
import { useBackendStatus } from "./useBackendStatus.ts"
import { useToasts } from "./use-toasts.ts"

vi.mock("./useBackendStatus.ts", () => ({ useBackendStatus: vi.fn(() => ({ backend: "online", agent: "offline" })) }))
vi.mock("./dock.tsx", () => ({ Dock: () => <div data-testid="dock" /> }))

function Page({ title }: { title: string }) {
  const { backend, agent } = useOutletContext<AppLayoutContext>()
  const { toasts, pushToast } = useToasts()
  return <section>
    <h1>{title}</h1>
    <p>Shared services: {backend}/{agent}</p>
    {toasts.map((toast) => <p key={toast.id}>{toast.message}</p>)}
    <button onClick={() => pushToast("success", "Persistent notification")}>Notify</button>
    <Link to="/projects/2">Open project</Link>
    <Link to="/settings">Open settings</Link>
  </section>
}

function renderLayout(entry: string) {
  render(<MemoryRouter initialEntries={[entry]}>
    <Routes>
      <Route element={<AppLayout />}>
        <Route element={<StandardLayout />}>
          <Route index element={<Page title="Home page" />} />
          <Route path="settings" element={<Page title="Settings page" />} />
        </Route>
        <Route path="projects/:id" element={<ProjectLayout />}>
          <Route index element={<Page title="Project detail" />} />
        </Route>
      </Route>
    </Routes>
  </MemoryRouter>)
}

beforeEach(() => vi.clearAllMocks())

describe("route layouts", () => {
  it("switches headers while retaining shared services, notifications and Dock", async () => {
    const user = userEvent.setup()
    renderLayout("/")
    expect(screen.getByRole("banner")).toBeDefined()
    expect(screen.getByText("Backend: Online")).toBeDefined()
    const dock = screen.getByTestId("dock")
    await user.click(screen.getByRole("button", { name: "Notify" }))
    await user.click(screen.getByRole("link", { name: "Open project" }))
    expect(screen.getByRole("heading", { name: "Project detail" })).toBeDefined()
    expect(screen.queryByRole("banner")).toBeNull()
    expect(screen.getByText("Shared services: online/offline")).toBeDefined()
    expect(screen.getByText("Persistent notification")).toBeDefined()
    expect(screen.getByTestId("dock")).toBe(dock)
    await user.click(screen.getByRole("link", { name: "Open settings" }))
    expect(screen.getByRole("heading", { name: "Settings page" })).toBeDefined()
    expect(screen.getByRole("navigation", { name: "Main navigation" })).toBeDefined()
    expect(screen.getByText("Persistent notification")).toBeDefined()
    expect(useBackendStatus).toHaveBeenCalledTimes(1)
  })

  it("opens project detail directly with shared status and one common container", () => {
    renderLayout("/projects/2")
    expect(screen.queryByRole("banner")).toBeNull()
    expect(screen.getByRole("main")).toHaveClass("app-project-layout")
    expect(screen.getByText("Shared services: online/offline")).toBeDefined()
    expect(screen.getAllByTestId("dock")).toHaveLength(1)
    expect(useBackendStatus).toHaveBeenCalledTimes(1)
  })
})
