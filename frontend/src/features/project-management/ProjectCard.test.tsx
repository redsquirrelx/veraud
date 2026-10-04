import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { ProjectCard } from "./ProjectCard.tsx"
import type { ProjectSummary } from "../../infrastructure/http-client/httpClient.ts"

const base: ProjectSummary = {
  id: 1,
  repositoryOwner: "acme",
  repositoryName: "Demo",
  status: "READY",
  registeredAt: "2026-01-01",
  branch: null,
  commitHash: null,
}

function renderCard(project: ProjectSummary) {
  render(
    <MemoryRouter>
      <ProjectCard project={project} />
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
        <ProjectCard project={base} />
      </MemoryRouter>
    )
    expect(screen.getByRole("button", { name: "acme/Demo" }).hasAttribute("disabled")).toBe(false)
    unmount()

    render(
      <MemoryRouter initialEntries={["/"]}>
        <ProjectCard project={{ ...base, status: "QUEUED" }} />
      </MemoryRouter>
    )
    expect(screen.getByRole("button", { name: "acme/Demo" }).hasAttribute("disabled")).toBe(true)
  })

  it("disables Inspect unless ready", () => {
    for (const status of ["QUEUED", "SYNCING"]) {
      const { unmount } = render(
        <MemoryRouter>
          <ProjectCard project={{ ...base, status }} />
        </MemoryRouter>
      )
      
      expect(screen.getByRole("button", { name: "Inspect" }).hasAttribute("disabled")).toBe(true)
      unmount()
    }
  })
})
