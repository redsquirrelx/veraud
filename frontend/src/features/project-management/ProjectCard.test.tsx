import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { ProjectCard } from "./ProjectCard.tsx"
import type { ProjectSummary } from "../../infrastructure/http-client/httpClient.ts"

const base: ProjectSummary = {
  id: 1,
  repositoryOwner: "acme",
  repositoryName: "Demo",
  status: "READY",
  registeredAt: "2026-01-01",
  lastSyncedAt: "2026-01-02",
  branch: null,
  commitHash: null,
}

function renderCard(project: ProjectSummary, pinned = false, onTogglePin: (id: number) => void = () => {}) {
  render(
    <MemoryRouter>
      <ProjectCard project={project} pinned={pinned} onTogglePin={onTogglePin} />
    </MemoryRouter>
  )
}

describe("ProjectCard", () => {
  it("shows owner/name with an enabled Inspect button when ready", () => {
    renderCard(base)

    expect(screen.getByText("acme/Demo")).toBeDefined()
    expect(screen.getByText("READY")).toBeDefined()
    expect(screen.getByRole("button", { name: "Inspect" }).hasAttribute("disabled")).toBe(false)
  })

  it("navigates through the title only when ready", () => {
    const { unmount } = render(
      <MemoryRouter initialEntries={["/"]}>
        <ProjectCard project={base} pinned={false} onTogglePin={() => {}} />
      </MemoryRouter>
    )
    expect(screen.getByRole("button", { name: "acme/Demo" }).hasAttribute("disabled")).toBe(false)
    unmount()

    render(
      <MemoryRouter initialEntries={["/"]}>
        <ProjectCard project={{ ...base, status: "QUEUED" }} pinned={false} onTogglePin={() => {}} />
      </MemoryRouter>
    )
    expect(screen.getByRole("button", { name: "acme/Demo" }).hasAttribute("disabled")).toBe(true)
  })

  it("disables Inspect unless ready", () => {
    for (const status of ["QUEUED", "SYNCING"]) {
      const { unmount } = render(
        <MemoryRouter>
          <ProjectCard project={{ ...base, status }} pinned={false} onTogglePin={() => {}} />
        </MemoryRouter>
      )
      expect(screen.getByRole("button", { name: "Inspect" }).hasAttribute("disabled")).toBe(true)
      unmount()
    }
  })

  it("toggles the pin with pressed state and handler", async () => {
    const toggled: number[] = []
    const { rerender } = render(
      <MemoryRouter>
        <ProjectCard project={base} pinned={false} onTogglePin={(id) => { toggled.push(id) }} />
      </MemoryRouter>
    )
    const pin = screen.getByRole("button", { name: "Pin project" })
    expect(pin.getAttribute("aria-pressed")).toBe("false")

    await userEvent.click(pin)
    expect(toggled).toEqual([1])

    rerender(
      <MemoryRouter>
        <ProjectCard project={base} pinned onTogglePin={() => {}} />
      </MemoryRouter>
    )
    expect(screen.getByRole("button", { name: "Unpin project" }).getAttribute("aria-pressed")).toBe("true")
  })

  it("keeps the pin enabled for non-ready projects", () => {
    renderCard({ ...base, status: "QUEUED" })

    expect(screen.getByRole("button", { name: "Pin project" }).hasAttribute("disabled")).toBe(false)
  })

  it("links to the GitHub repository in a new tab", () => {
    renderCard(base)

    const link = screen.getByRole("link", { name: "Open acme/Demo on GitHub" })
    expect(link.getAttribute("href")).toBe("https://github.com/acme/Demo")
    expect(link.getAttribute("target")).toBe("_blank")
    expect(link.getAttribute("rel")).toContain("noreferrer")
  })
})
