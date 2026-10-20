import { afterEach, describe, expect, it } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { AuditStatusDrawer } from "./AuditStatusDrawer.tsx"
import { changeLanguage } from "../i18n/index.ts"
import type { AuditStatusModel } from "./auditStatus.ts"

const running: AuditStatusModel = {
  id: 41,
  project: { id: 5, repositoryOwner: "acme", repositoryName: "Payments" },
  branch: "main",
  commitHash: "9f2c1ab7de4d0c6b5a8391f4e2d7c8b0a6e5f4d3",
  state: "running",
  error: null,
  createdAt: "2026-10-17T10:00:00Z",
  finishedAt: null,
  reportAvailable: false,
  pipelines: [{
    id: "maintainability",
    state: "running",
    agents: [{
      id: 118, agentType: "maintainability_manager", state: "completed",
      inputTokens: 41230, outputTokens: 9840,
      startedAt: "2026-10-17T10:00:12Z", finishedAt: "2026-10-17T10:04:41Z", error: null,
    }],
  }],
}

const completed: AuditStatusModel = {
  ...running,
  id: 40,
  project: { id: 12, repositoryOwner: "acme", repositoryName: "Ledger" },
  state: "completed",
  finishedAt: "2026-10-16T08:41:27Z",
  reportAvailable: true,
  pipelines: [{ id: "security", state: "completed", agents: [] }],
}

function show(audits: AuditStatusModel[]) {
  render(
    <MemoryRouter>
      <AuditStatusDrawer audits={audits} />
    </MemoryRouter>,
  )
}

/** The closed panel is inert, so role queries cannot reach it: read it directly. */
function panelElement(): HTMLElement {
  const found = document.querySelector<HTMLElement>(".audit-drawer-panel")
  if (found === null) {
    throw new Error("Missing audit drawer panel")
  }
  return found
}

/** The tab and the panel share this shell, which is what slides in and out. */
function shellElement(): HTMLElement {
  const found = document.querySelector<HTMLElement>(".audit-drawer-shell")
  if (found === null) {
    throw new Error("Missing audit drawer shell")
  }
  return found
}

function openPanel(name: string) {
  return screen.getByRole("region", { name })
}

describe("AuditStatusDrawer", () => {
  it("starts closed and keeps the panel out of the accessibility tree", () => {
    show([running, completed])
    const trigger = screen.getByRole("button", { name: "2 audits" })

    expect(trigger).toHaveAttribute("aria-expanded", "false")
    expect(trigger.getAttribute("aria-controls")).toBe(panelElement().id)
    expect(panelElement()).toHaveAttribute("aria-hidden", "true")
    expect(panelElement()).toHaveAttribute("inert")
    expect(shellElement()).toHaveAttribute("data-open", "false")
    // The panel role is unreachable while inert.
    expect(screen.queryByRole("region", { name: "Audit statuses" })).toBeNull()
  })

  it("puts the tab in the sliding shell, beside the panel it controls", () => {
    show([running])

    const shell = shellElement()
    // Tab first, then panel: the tab sits on the panel's outer edge.
    expect(Array.from(shell.children).map((child) => child.className)).toEqual([
      "audit-drawer-trigger",
      "audit-drawer-panel",
    ])
    expect(shell.contains(document.querySelector(".audit-drawer-trigger"))).toBe(true)
  })

  it("counts the audits on the tab in both numbers", () => {
    show([running, completed])
    expect(screen.getByRole("button", { name: "2 audits" })).toBeInTheDocument()

    show([running])
    expect(screen.getByRole("button", { name: "1 audit" })).toBeInTheDocument()
  })

  it("marks the tab while an audit is running or queued", () => {
    const { container } = render(
      <MemoryRouter>
        <AuditStatusDrawer audits={[running]} />
      </MemoryRouter>,
    )
    expect(container.querySelector(".audit-drawer-trigger-active")).not.toBeNull()

    const settled = render(
      <MemoryRouter>
        <AuditStatusDrawer audits={[completed]} />
      </MemoryRouter>,
    )
    expect(settled.container.querySelector(".audit-drawer-trigger-active")).toBeNull()
  })

  it("reveals every audit stacked in the panel", async () => {
    show([running, completed])
    await userEvent.click(screen.getByRole("button", { name: "2 audits" }))

    expect(screen.getByRole("button", { name: "2 audits" })).toHaveAttribute("aria-expanded", "true")
    expect(panelElement()).toHaveAttribute("aria-hidden", "false")
    expect(shellElement()).toHaveAttribute("data-open", "true")
    expect(panelElement()).not.toHaveAttribute("inert")

    const panel = openPanel("Audit statuses")
    expect(within(panel).getByText("Audit #41")).toBeInTheDocument()
    expect(within(panel).getByText("Audit #40")).toBeInTheDocument()
    // Each audit keeps its own project link.
    expect(within(panel).getByRole("link", { name: "Open acme/Payments" })).toHaveAttribute("href", "/projects/5/audits")
    expect(within(panel).getByRole("link", { name: "Open acme/Ledger" })).toHaveAttribute("href", "/projects/12/audits")
  })

  it("closes from the header button and from Escape", async () => {
    show([running])
    const trigger = screen.getByRole("button", { name: "1 audit" })

    await userEvent.click(trigger)
    await userEvent.click(within(openPanel("Audit statuses")).getByRole("button", { name: "Close" }))
    expect(trigger).toHaveAttribute("aria-expanded", "false")

    await userEvent.click(trigger)
    await userEvent.keyboard("{Escape}")
    expect(trigger).toHaveAttribute("aria-expanded", "false")
  })

  it("moves focus into the panel and back to the tab", async () => {
    show([running])
    const trigger = screen.getByRole("button", { name: "1 audit" })

    trigger.focus()
    await userEvent.keyboard("{Enter}")
    expect(panelElement()).toHaveFocus()

    await userEvent.keyboard("{Escape}")
    expect(trigger).toHaveFocus()
  })

  it("never steals focus on mount while closed", () => {
    const outside = document.createElement("button")
    document.body.append(outside)
    outside.focus()

    show([running])

    expect(outside).toHaveFocus()
    outside.remove()
  })

  it("does not trap focus or lock the page behind it", async () => {
    show([running])
    const trigger = screen.getByRole("button", { name: "1 audit" })
    await userEvent.click(trigger)

    expect(panelElement().getAttribute("aria-modal")).toBeNull()
    expect(document.body.style.overflow).toBe("")

    // Focus walks through the panel and then escapes instead of cycling in it.
    expect(panelElement()).toHaveFocus()
    await userEvent.tab()
    expect(within(openPanel("Audit statuses")).getByRole("button", { name: "Close" })).toHaveFocus()
    await userEvent.tab({ shift: true })
    expect(trigger).toHaveFocus()
  })

  it("folds finished audits and leaves the unfinished ones open", async () => {
    show([running, completed])
    await userEvent.click(screen.getByRole("button", { name: "2 audits" }))

    const toggles = document.querySelectorAll(".audit-disclosure-toggle")
    expect(toggles[0]).toHaveAttribute("aria-expanded", "true")
    expect(toggles[1]).toHaveAttribute("aria-expanded", "false")

    const details = document.querySelectorAll(".audit-disclosure-detail")
    expect(details[0]).toHaveAttribute("aria-hidden", "false")
    expect(details[1]).toHaveAttribute("aria-hidden", "true")
  })

  it("shows an empty state when there are no audits", async () => {
    show([])
    await userEvent.click(screen.getByRole("button", { name: "0 audits" }))

    expect(within(openPanel("Audit statuses")).getByText("No audits to show")).toBeInTheDocument()
  })
})

describe("AuditStatusDrawer Spanish", () => {
  afterEach(async () => {
    await changeLanguage("en")
  })

  it("translates the tab, the panel and its audits", async () => {
    await changeLanguage("es")

    show([running])
    await userEvent.click(screen.getByRole("button", { name: "1 auditoría" }))

    const panel = openPanel("Estados de auditoría")
    expect(within(panel).getByText("Auditoría #41")).toBeInTheDocument()
    expect(within(panel).getByRole("button", { name: "Cerrar" })).toBeInTheDocument()
    expect(within(panel).getByRole("link", { name: "Abrir acme/Payments" })).toHaveAttribute("href", "/projects/5/audits")
  })
})