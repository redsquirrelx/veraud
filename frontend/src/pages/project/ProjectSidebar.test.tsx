import { beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Outlet, Route, Routes } from "react-router-dom"
import { FolderIcon } from "../../shared/ui-kit/index.ts"
import { ProjectSidebar } from "./ProjectSidebar.tsx"

const items = ["Overview", "Audits", "Files"].map((label) => ({ id: label.toLowerCase(), label, icon: <FolderIcon /> }))

function renderSidebar(onSelect = vi.fn()) {
  return render(<MemoryRouter initialEntries={["/projects/2"]}>
    <Routes>
      <Route element={<Outlet context={{ backend: "online", agent: "offline" }} />}>
        <Route path="projects/:id" element={<ProjectSidebar items={items} activeId="overview" onSelect={onSelect} />} />
      </Route>
    </Routes>
  </MemoryRouter>)
}

beforeEach(() => window.localStorage.clear())

describe("ProjectSidebar", () => {
  it("separates page links, project sections, documentation and shared service status", async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()
    renderSidebar(onSelect)
    expect(screen.getByRole("link", { name: "Veraud" })).toHaveAttribute("href", "/")
    expect(screen.getByRole("link", { name: "Home" })).not.toHaveAttribute("aria-current")
    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("href", "/settings")
    expect(screen.getByRole("button", { name: "Overview" })).toHaveAttribute("aria-current", "page")
    await user.click(screen.getByRole("button", { name: "Audits" }))
    expect(onSelect).toHaveBeenCalledWith("audits")
    expect(screen.getByText("Backend: Online")).toBeDefined()
    expect(screen.getByText("Agents Server: Offline")).toBeDefined()
    await user.click(screen.getByRole("button", { name: "API docs" }))
    expect(screen.getByRole("link", { name: /WebSocket docs/ })).toHaveAttribute("href", "http://localhost:7501/docs/ws")
    expect(screen.getByRole("link", { name: /Backend docs/ })).toHaveAttribute("target", "_blank")
  })

  it("retains named controls and keyboard documentation access after persisted collapse", async () => {
    const user = userEvent.setup()
    const { unmount } = renderSidebar()
    await user.click(screen.getByRole("button", { name: "Collapse sidebar" }))
    unmount()
    renderSidebar()
    expect(screen.getByRole("button", { name: "Expand sidebar" })).toBeDefined()
    expect(screen.getByRole("link", { name: "Home" })).toHaveAttribute("title", "Home")
    expect(screen.getByRole("button", { name: "Files" })).toHaveAttribute("title", "Files")
    expect(screen.getByLabelText("Backend: Online")).toHaveAttribute("title", "Backend: Online")
    const docs = screen.getByRole("button", { name: "API docs" })
    docs.focus()
    await user.keyboard("{ArrowDown}")
    expect(screen.getByRole("link", { name: /Backend docs/ })).toHaveFocus()
    await user.keyboard("{Escape}")
    expect(docs).toHaveFocus()
    expect(screen.queryByRole("link", { name: /Backend docs/ })).toBeNull()
  })
})
