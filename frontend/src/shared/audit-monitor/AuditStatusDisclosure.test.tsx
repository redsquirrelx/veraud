import { afterEach, describe, expect, it } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { AuditStatusDisclosure } from "./AuditStatusDisclosure.tsx"
import { changeLanguage } from "../i18n/index.ts"
import type { AuditStatusModel } from "./auditStatus.ts"

const completed: AuditStatusModel = {
  id: 40,
  project: { id: 12, repositoryOwner: "acme", repositoryName: "Ledger" },
  branch: "main",
  commitHash: "3b7e5f0a1c9d8e2f4a6b0c3d5e7f9a1b3c5d7e9f",
  state: "completed",
  error: null,
  createdAt: "2026-10-16T08:30:00Z",
  finishedAt: "2026-10-16T08:41:27Z",
  reportAvailable: true,
  pipelines: [{
    id: "security",
    state: "completed",
    agents: [{
      id: 114, agentType: "security_scanner", state: "completed",
      inputTokens: 31500, outputTokens: 6980,
      startedAt: "2026-10-16T08:30:11Z", finishedAt: "2026-10-16T08:33:47Z", error: null,
    }],
  }],
}

const running: AuditStatusModel = {
  ...completed,
  id: 41,
  project: { id: 5, repositoryOwner: "acme", repositoryName: "Payments" },
  state: "running",
  finishedAt: null,
  reportAvailable: false,
}

function show(audit: AuditStatusModel, defaultExpanded?: boolean) {
  render(
    <MemoryRouter>
      <AuditStatusDisclosure audit={audit} defaultExpanded={defaultExpanded} />
    </MemoryRouter>,
  )
  return document.querySelector<HTMLButtonElement>(".audit-disclosure-toggle")!
}

function detail(): HTMLElement {
  const found = document.querySelector<HTMLElement>(".audit-disclosure-detail")
  if (found === null) {
    throw new Error("Missing disclosure detail")
  }
  return found
}

describe("AuditStatusDisclosure", () => {
  it("folds and unfolds from its summary row", async () => {
    const toggle = show(completed, false)

    expect(toggle).toHaveAttribute("aria-expanded", "false")
    await userEvent.click(toggle)
    expect(toggle).toHaveAttribute("aria-expanded", "true")
    expect(detail()).toHaveAttribute("data-expanded", "true")

    await userEvent.click(toggle)
    expect(toggle).toHaveAttribute("aria-expanded", "false")
    expect(detail()).toHaveAttribute("aria-hidden", "true")
    expect(detail()).toHaveAttribute("inert")
  })

  it("summarises the audit without opening it", () => {
    const toggle = show(completed, false)

    // Identity, state and progress stay visible while folded.
    expect(toggle).toHaveAccessibleName("Audit #40 · Completed · 1 of 1 agents")
    expect(screen.getByRole("link", { name: "Open acme/Ledger" })).toHaveAttribute("href", "/projects/12/audits")
    expect(detail()).toHaveAttribute("aria-hidden", "true")
    expect(detail()).toHaveAttribute("inert")
  })

  it("splits the summary across two rows instead of one crowded line", () => {
    show(completed, false)
    const toggle = document.querySelector(".audit-disclosure-toggle")!

    const lines = toggle.querySelectorAll(".audit-disclosure-line")
    expect(lines).toHaveLength(2)
    expect(within(lines[0] as HTMLElement).getByText("Audit #40")).toBeInTheDocument()
    expect(within(lines[1] as HTMLElement).getByText("Completed")).toBeInTheDocument()
    expect(within(lines[1] as HTMLElement).getByText("1 of 1 agents")).toBeInTheDocument()
    expect(within(lines[1] as HTMLElement).getByText("Report available")).toBeInTheDocument()
  })

  it("keeps the project link outside the toggle so it cannot squeeze it", () => {
    show(completed, false)
    const head = document.querySelector(".audit-disclosure-head")!
    const toggle = document.querySelector(".audit-disclosure-toggle")!
    const link = screen.getByRole("link", { name: "Open acme/Ledger" })

    // A link inside the toggle is invalid HTML, and as a sibling on the same
    // row its content width would starve the badges. It gets its own row.
    expect(Array.from(head.children)).toEqual([link, toggle])
    expect(toggle.contains(link)).toBe(false)
    expect(head.contains(toggle)).toBe(true)
  })

  it("keeps folded agents mounted but out of the accessibility tree", () => {
    show(completed, false)

    const agent = screen.getByText("security_scanner run #114", { selector: ".audit-agent-type" })

    expect(detail().contains(agent)).toBe(true)
    expect(detail()).toHaveAttribute("inert")
  })

  it("shows the identity once, whether folded or open", async () => {
    const toggle = show(completed, false)
    expect(screen.getAllByText("Audit #40")).toHaveLength(1)
    expect(screen.getAllByRole("link", { name: "Open acme/Ledger" })).toHaveLength(1)

    await userEvent.click(toggle)

    // Opening reveals pipelines without repeating the summary row above it.
    expect(screen.getAllByText("Audit #40")).toHaveLength(1)
    expect(screen.getAllByRole("link", { name: "Open acme/Ledger" })).toHaveLength(1)
    expect(screen.getByText("security_scanner run #114")).toBeInTheDocument()
  })

  it("honours the caller's initial state", () => {
    expect(show(completed, false)).toHaveAttribute("aria-expanded", "false")
    expect(screen.getByText("security_scanner run #114")).toBeInTheDocument()
  })

  it("keeps the project link outside the toggle", () => {
    show(completed, false)
    const toggle = document.querySelector(".audit-disclosure-toggle")
    const link = screen.getByRole("link", { name: "Open acme/Ledger" })

    expect(toggle?.contains(link)).toBe(false)
    expect(toggle?.parentElement?.contains(link)).toBe(true)
  })

  it("exposes its state so the card can carry the accent", () => {
    show(completed)
    expect(document.querySelector(".audit-disclosure")).toHaveAttribute("data-state", "completed")
  })

  it("opens and closes with the keyboard", async () => {
    const toggle = show(completed, false)

    toggle.focus()
    await userEvent.keyboard("{Enter}")
    expect(toggle).toHaveAttribute("aria-expanded", "true")
    await userEvent.keyboard(" ")
    expect(toggle).toHaveAttribute("aria-expanded", "false")
  })

  it("opens by default unless the caller asks otherwise", async () => {
    const toggle = show(running)
    expect(toggle).toHaveAttribute("aria-expanded", "true")
    expect(screen.getByText("security_scanner run #114")).toBeInTheDocument()
  })

  it("surfaces an audit error only once the audit is opened", async () => {
    const toggle = show({ ...completed, state: "failed", error: "The security pipeline could not be started." }, false)

    // Rendered but hidden, so a failed audit only announces its problem once read.
    expect(detail().textContent).toContain("The security pipeline could not be started.")
    expect(screen.queryByRole("alert")).toBeNull()

    await userEvent.click(toggle)

    expect(screen.getByRole("alert")).toHaveTextContent("The security pipeline could not be started.")
  })
})

describe("AuditStatusDisclosure Spanish", () => {
  afterEach(async () => {
    await changeLanguage("en")
  })

  it("translates the summary while keeping the identifier", async () => {
    await changeLanguage("es")

    const toggle = show(completed, false)

    expect(toggle).toHaveAccessibleName("Auditoría #40 · Completada · 1 de 1 agentes")
    expect(screen.getByRole("link", { name: "Abrir acme/Ledger" })).toBeInTheDocument()
  })
})