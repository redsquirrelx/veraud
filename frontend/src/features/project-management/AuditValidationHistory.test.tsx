import { afterEach, describe, expect, it } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { changeLanguage } from "../../shared/i18n/index.ts"
import { AuditValidationHistory, AuditValidationHistoryPreview, type AuditRevalidation } from "./AuditValidationHistory.tsx"

const audit = { createdAt: "2026-10-17T10:00:00Z", startedAt: "2026-10-17T10:05:00Z" }
const revisions: AuditRevalidation[] = [
  { id: "second", parentId: null, createdAt: "2026-10-19T10:00:00Z", commitHash: "b".repeat(40) },
  { id: "fourth", parentId: "third", createdAt: "2026-10-21T10:00:00Z", commitHash: "d".repeat(40) },
  { id: "third", parentId: "first", createdAt: "2026-10-20T10:00:00Z", commitHash: "c".repeat(40) },
  { id: "first", parentId: null, createdAt: "2026-10-18T10:00:00Z", commitHash: "a".repeat(40) },
]

afterEach(async () => { await changeLanguage("en") })

describe("AuditValidationHistory", () => {
  it("replaces history with the chosen revalidation details and returns to the previous branch state", async () => {
    const user = userEvent.setup()
    render(<AuditValidationHistoryPreview />)
    await user.click(screen.getByRole("button", { name: "Hide revalidations of Revalidation #3" }))
    const node = within(screen.getByText("Revalidation #2").closest(".audit-validation-node") as HTMLElement)
    const hash = node.getByLabelText(/^Commit:/).getAttribute("title")!
    await user.click(node.getByRole("button", { name: "View details" }))
    const detail = within(screen.getByRole("region", { name: "Revalidation #2" }))
    expect(screen.queryByRole("region", { name: "Validation history" })).toBeNull()
    expect(detail.getByRole("heading", { name: "Revalidation #2" })).toHaveFocus()
    expect(detail.getByText("Completed")).toHaveClass("ui-badge-content")
    expect(detail.getByText(`Commit ${hash.slice(0, 7)}`)).toHaveAttribute("title", hash)
    const summary = within(detail.getByLabelText("Revalidation summary"))
    expect(detail.getByLabelText("Revalidation summary").querySelector(".ui-badge")).toBeNull()
    for (const [label, total] of [["Resolved", "5"], ["Persistent", "2"], ["Inconclusive", "1"]]) {
      expect(within(summary.getByText(label).closest("div")!).getByRole("definition")).toHaveTextContent(total)
    }
    const findings = within(detail.getByRole("region", { name: "Revalidated findings" }))
    expect(findings.getAllByRole("listitem")).toHaveLength(8)
    expect(findings.getAllByText("Resolved")).toHaveLength(5)
    expect(findings.getAllByText("Persistent")).toHaveLength(2)
    expect(findings.getAllByText("Inconclusive")).toHaveLength(1)
    expect(detail.getByText("Conceptual view with sample data.")).toBeVisible()
    await user.click(detail.getByRole("button", { name: "Back to history" }))
    expect(screen.getByRole("region", { name: "Validation history" })).toBeVisible()
    expect(screen.getByRole("button", { name: "Show revalidations of Revalidation #3" })).toHaveAttribute("aria-expanded", "false")
    expect(screen.getByText("Revalidation #6")).not.toBeVisible()
    expect(screen.queryByRole("region", { name: "Revalidation #2" })).toBeNull()
  })

  it("localizes details and uses the selected node rather than a fixed revalidation", async () => {
    await changeLanguage("es")
    const user = userEvent.setup()
    render(<AuditValidationHistoryPreview />)
    const node = within(screen.getByText("Revalidation #7").closest(".audit-validation-node") as HTMLElement)
    await user.click(node.getByRole("button", { name: "Ver detalle" }))
    const detail = within(screen.getByRole("region", { name: "Revalidation #7" }))
    expect(detail.getByText("Completada").closest(".ui-badge")).toHaveClass("ui-badge-success")
    const findings = within(detail.getByRole("region", { name: "Hallazgos revalidados" }))
    expect(findings.getByRole("heading", { name: "Violación de límites de arquitectura" })).toBeVisible()
    expect(findings.getAllByText("Resuelto")[0].closest(".ui-badge")).toHaveClass("ui-badge-success")
    expect(findings.getAllByText("Persistente")[0].closest(".ui-badge")).toHaveClass("ui-badge-danger")
    expect(findings.getByText("No concluyente").closest(".ui-badge")).toHaveClass("ui-badge-warning")
    await user.click(detail.getByRole("button", { name: "Volver al historial" }))
    expect(screen.getByRole("region", { name: "Historial de validación" })).toBeVisible()
  })

  it("opens the shared modal for the chosen revalidation and enables its mock form after selecting a target", async () => {
    const user = userEvent.setup()
    render(<AuditValidationHistoryPreview />)
    const node = within(screen.getByText("Revalidation #3").closest(".audit-validation-node") as HTMLElement)
    const hash = node.getByLabelText(/^Commit:/).getAttribute("title")!
    const trigger = node.getByRole("button", { name: "+ New revalidation" })
    await user.click(trigger)
    const dialog = within(screen.getByRole("dialog", { name: "New revalidation" }))
    expect(dialog.getByText("Verify remaining findings against a newer commit.")).toBeVisible()
    expect(dialog.getByText(hash.slice(0, 7))).toHaveAttribute("title", hash)
    expect(dialog.getByText("Revalidation #3")).toBeVisible()
    const select = dialog.getByRole("button", { name: "Select a newer commit…" })
    expect(select).toHaveFocus()
    expect(select).toHaveAccessibleDescription("Select target commit")
    const start = dialog.getByRole("button", { name: "Start revalidation" })
    expect(start).toBeDisabled()
    await user.click(select)
    await user.click(dialog.getAllByRole("option")[0])
    expect(start).toBeEnabled()
    await user.click(start)
    expect(dialog.getByRole("status")).toHaveTextContent("This is a mockup. No revalidation has been started.")
    expect(screen.getAllByRole("listitem")).toHaveLength(8)
    await user.keyboard("{Escape}")
    expect(screen.queryByRole("dialog")).toBeNull()
    expect(trigger).toHaveFocus()
    await user.click(trigger)
    expect(screen.getByRole("button", { name: "Start revalidation" })).toBeDisabled()
  })

  it("opens a localized form from another branch and closes via the Modal close button", async () => {
    await changeLanguage("es")
    const user = userEvent.setup()
    render(<AuditValidationHistoryPreview />)
    const node = within(screen.getByText("Revalidation #5").closest(".audit-validation-node") as HTMLElement)
    await user.click(node.getByRole("button", { name: "+ Nueva revalidación" }))
    const dialog = within(screen.getByRole("dialog", { name: "Nueva revalidación" }))
    expect(dialog.getByText("Último commit evaluado")).toBeVisible()
    expect(dialog.getByText("Revalidation #5")).toBeVisible()
    const selector = dialog.getByRole("button", { name: "Selecciona un commit más reciente…" })
    expect(selector).toHaveAccessibleDescription("Seleccionar commit de destino")
    expect(selector).toHaveAttribute("aria-expanded", "false")
    expect(dialog.getByRole("button", { name: "Iniciar revalidación" })).toBeDisabled()
    await user.click(dialog.getByRole("button", { name: "Cerrar" }))
    expect(screen.queryByRole("dialog")).toBeNull()
  })

  it("provides a clearly marked mockup with multiple branches and nested revalidations", () => {
    render(<AuditValidationHistoryPreview />)
    expect(screen.getByText("Sample data")).toBeVisible()
    expect(screen.getAllByRole("listitem")).toHaveLength(8)
    const first = screen.getByText("Revalidation #1").closest("li")!
    expect(first.querySelector(":scope > ol")?.children).toHaveLength(2)
    const sixth = screen.getByText("Revalidation #6").closest("li")!
    expect(within(sixth).getByText("Revalidation #7")).toBeVisible()
  })

  it("starts with only the actual initial audit, without invented revalidations", () => {
    render(<AuditValidationHistory audit={audit} />)
    expect(screen.getByRole("region", { name: "Validation history" })).toBeVisible()
    expect(screen.getAllByRole("listitem")).toHaveLength(1)
    expect(screen.getByText("Initial Audit")).toBeVisible()
    expect(screen.queryByText(/Revalidation #/)).toBeNull()
    expect(screen.getByText("Initial Audit").parentElement?.querySelector("time"))
      .toHaveAttribute("dateTime", audit.startedAt)
  })

  it("places icons and numbered markers outside the cards along connected branch rails", () => {
    render(<AuditValidationHistory audit={audit} revalidations={revisions} />)
    const rootRow = screen.getByText("Initial Audit").closest(".audit-validation-row")!
    expect(rootRow).toHaveAttribute("data-has-children", "true")
    expect(rootRow.querySelector(".audit-validation-marker svg")).toBeInTheDocument()
    const firstRow = screen.getByText("Revalidation #1").closest(".audit-validation-row")!
    const marker = firstRow.querySelector(".audit-validation-marker")!
    expect(marker).toHaveTextContent("1")
    expect(marker).toHaveAttribute("aria-expanded", "true")
    expect(firstRow.querySelector(".audit-validation-node")).not.toContainElement(marker as HTMLElement)
    expect(firstRow).toHaveAttribute("data-has-children", "true")
    const latestRow = screen.getByText("Revalidation #4").closest(".audit-validation-row")!
    expect(latestRow).toHaveAttribute("data-has-children", "false")
    expect(latestRow).toHaveAttribute("data-latest", "true")
  })

  it("preserves parent branches and supports revalidations of revalidations at multiple levels", () => {
    render(<AuditValidationHistory audit={audit} revalidations={revisions} />)
    const root = screen.getByText("Initial Audit").closest("li")!
    const first = screen.getByText("Revalidation #1").closest("li")!
    const second = screen.getByText("Revalidation #2").closest("li")!
    const third = screen.getByText("Revalidation #3").closest("li")!
    const fourth = screen.getByText("Revalidation #4").closest("li")!
    expect(root.querySelector(":scope > ol")?.children).toHaveLength(2)
    expect(first.parentElement).toBe(second.parentElement)
    expect(third.parentElement?.parentElement).toBe(first)
    expect(fourth.parentElement?.parentElement).toBe(third)
    expect(within(second).queryByRole("list")).toBeNull()
  })

  it("collapses only the chosen branch and preserves nested collapse state when it is reopened", async () => {
    const user = userEvent.setup()
    render(<AuditValidationHistoryPreview />)
    const third = screen.getByRole("button", { name: "Hide revalidations of Revalidation #3" })
    await user.click(third)
    expect(third).toHaveAttribute("aria-expanded", "false")
    expect(screen.getByText("Revalidation #6")).not.toBeVisible()
    expect(screen.getByText("Revalidation #7")).not.toBeVisible()
    expect(screen.getByText("Revalidation #4")).toBeVisible()
    await user.click(screen.getByRole("button", { name: "Hide revalidations of Revalidation #1" }))
    expect(screen.getByText("Revalidation #3")).not.toBeVisible()
    expect(screen.getByText("Revalidation #2")).toBeVisible()
    expect(screen.getByText("Revalidation #5")).toBeVisible()
    await user.click(screen.getByRole("button", { name: "Show revalidations of Revalidation #1" }))
    expect(screen.getByText("Revalidation #3")).toBeVisible()
    expect(screen.getByText("Revalidation #6")).not.toBeVisible()
    await user.click(screen.getByRole("button", { name: "Show revalidations of Revalidation #3" }))
    expect(screen.getByText("Revalidation #7")).toBeVisible()
    expect(screen.getAllByText("Latest")).toHaveLength(3)
  })

  it("can toggle the entire tree from Initial Audit using the keyboard", async () => {
    const user = userEvent.setup()
    render(<AuditValidationHistoryPreview />)
    const root = screen.getByRole("button", { name: "Hide revalidations of Initial Audit" })
    root.focus()
    await user.keyboard("{Enter}")
    expect(root).toHaveAttribute("aria-expanded", "false")
    expect(document.getElementById(root.getAttribute("aria-controls")!)).toHaveAttribute("hidden")
    expect(screen.getByText("Revalidation #1")).not.toBeVisible()
    expect(screen.getByText("Initial Audit")).toBeVisible()
    await user.keyboard(" ")
    expect(root).toHaveAttribute("aria-expanded", "true")
    expect(screen.getByText("Revalidation #7")).toBeVisible()
  })

  it("marks every branch tip as Latest rather than only the globally newest revalidation", () => {
    render(<AuditValidationHistoryPreview />)
    expect(screen.getAllByText("Latest")).toHaveLength(3)
    for (const number of [4, 5, 7]) {
      const node = screen.getByText(`Revalidation #${number}`).closest(".audit-validation-node")!
      expect(within(node as HTMLElement).getByText("Latest")).toBeVisible()
      const badge = within(node as HTMLElement).getByText("Latest").closest(".ui-badge")!
      expect(badge).toHaveClass("ui-badge-success")
      expect(badge).not.toHaveClass("ui-badge-compact")
      expect(node.closest(".audit-validation-row")).toHaveAttribute("data-latest", "true")
    }
    for (const number of [1, 2, 3, 6]) {
      const node = screen.getByText(`Revalidation #${number}`).closest(".audit-validation-node")!
      expect(within(node as HTMLElement).queryByText("Latest")).toBeNull()
      expect(node.closest(".audit-validation-row")).toHaveAttribute("data-latest", "false")
    }
  })

  it("shows each commit and primary/secondary mockup actions on every revalidation", async () => {
    await changeLanguage("es")
    render(<AuditValidationHistory audit={audit} revalidations={revisions} />)
    expect(screen.getAllByRole("button", { name: "+ Nueva revalidación" })).toHaveLength(4)
    expect(screen.getAllByRole("button", { name: "Ver detalle" })).toHaveLength(4)
    for (const revision of revisions) {
      const commit = screen.getByLabelText(`Commit: ${revision.commitHash}`)
      expect(commit).toHaveTextContent(revision.commitHash.slice(0, 7))
      expect(commit).toHaveAttribute("title", revision.commitHash)
      const node = within(commit.closest(".audit-validation-node") as HTMLElement)
      expect(node.getByRole("button", { name: "+ Nueva revalidación" })).toHaveClass("ui-button-primary")
      expect(node.getByRole("button", { name: "Ver detalle" })).toHaveClass("ui-button-secondary")
    }
  })

  it("sorts siblings chronologically and numbers globally without mutating history", () => {
    const original = revisions.map((item) => item.id)
    render(<AuditValidationHistory audit={audit} revalidations={revisions} />)
    const root = screen.getByText("Initial Audit").closest("li")!
    const siblings = Array.from(root.querySelector(":scope > ol")!.children)
    expect(siblings.map((item) => item.querySelector("strong")?.textContent))
      .toEqual(["Revalidation #1", "Revalidation #2"])
    expect(screen.getAllByText(/Revalidation #/).map((item) => item.textContent))
      .toEqual(["Revalidation #1", "Revalidation #3", "Revalidation #4", "Revalidation #2"])
    expect(revisions.map((item) => item.id)).toEqual(original)
    expect(screen.getByText("Revalidation #3").closest(".audit-validation-node")?.querySelector("time"))
      .toHaveAttribute("dateTime", "2026-10-20T10:00:00Z")
  })

  it("uses the creation date when the initial audit has no start date", () => {
    render(<AuditValidationHistory audit={{ ...audit, startedAt: null }} />)
    expect(screen.getByText("Initial Audit").parentElement?.querySelector("time"))
      .toHaveAttribute("dateTime", audit.createdAt)
  })

  it("does not render an invalid date", () => {
    render(<AuditValidationHistory audit={{ createdAt: "invalid", startedAt: null }} />)
    expect(screen.getByText("Initial Audit")).toBeVisible()
    expect(screen.getByText("Initial Audit").parentElement?.querySelector("time")).toBeNull()
  })

  it("localizes the section title while keeping the requested item names", async () => {
    await changeLanguage("es")
    render(<AuditValidationHistory audit={audit} revalidations={revisions} />)
    expect(screen.getByRole("region", { name: "Historial de validación" })).toBeVisible()
    expect(screen.getByText("Initial Audit")).toBeVisible()
    expect(screen.getByText("Revalidation #1")).toBeVisible()
  })
})
