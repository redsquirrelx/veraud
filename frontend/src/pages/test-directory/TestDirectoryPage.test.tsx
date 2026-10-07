import { describe, expect, it } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { TestDirectoryPage } from "./TestDirectoryPage.tsx"

function card(index: number): HTMLElement {
  const list = screen.getAllByRole("tree")[index]
  const found = list?.closest(".ui-card")
  if (found === null || found === undefined) {
    throw new Error(`card ${index} not found`)
  }
  return found as HTMLElement
}

function rowsIn(index: number): HTMLElement {
  const list = screen.getAllByRole("tree")[index]
  if (list === undefined) {
    throw new Error(`tree ${index} not found`)
  }
  return list
}

function selectedNamesIn(index: number): string[] {
  return Array.from(rowsIn(index).querySelectorAll('[role="treeitem"][aria-selected="true"]'))
    .map((item) => item.textContent ?? "")
}

function renderPage() {
  render(
    <MemoryRouter>
      <TestDirectoryPage />
    </MemoryRouter>
  )
}

describe("TestDirectoryPage", () => {
  it("shows the plain tree without any tag", () => {
    renderPage()

    expect(screen.getByText("Directory playground")).toBeDefined()
    expect(screen.getByText("Project Structure")).toBeDefined()
    expect(within(rowsIn(0)).getByText("modules")).toBeDefined()
    expect(within(rowsIn(0)).queryByText("flagged")).toBeNull()
    expect(rowsIn(0).querySelectorAll(".directory-tag").length).toBe(0)
  })

  it("collapses and expands a folder", async () => {
    renderPage()

    await userEvent.click(within(rowsIn(0)).getByText("modules"))

    expect(within(rowsIn(0)).queryByText("settlement.ts")).toBeNull()

    await userEvent.click(within(rowsIn(0)).getByText("modules"))

    expect(within(rowsIn(0)).getByText("settlement.ts")).toBeDefined()
  })

  it("selects a file and reflects it in the breadcrumb", async () => {
    renderPage()

    await userEvent.click(within(rowsIn(0)).getByText("ledger.repository.ts"))

    const nav = within(card(0)).getByRole("navigation", { name: "Breadcrumb" })
    expect(Array.from(nav.querySelectorAll(".directory-crumb")).map((crumb) => crumb.textContent))
      .toEqual(["payment-gateway-v2", "src", "modules", "ledger.repository.ts"])
    expect(selectedNamesIn(0).join()).toContain("ledger.repository.ts")
  })

  it("reveals nested folders on demand", async () => {
    renderPage()

    expect(within(rowsIn(0)).getByText("reconciliation")).toBeDefined()

    await userEvent.click(within(rowsIn(0)).getByText("reconciliation"))

    expect(within(rowsIn(0)).getByText("engine.test.ts")).toBeDefined()
  })

  it("colours grouped directories in the second instance", () => {
    renderPage()

    const grouped = rowsIn(1)

    expect(within(grouped).getAllByText("critical").length).toBe(3)
    expect(within(grouped).getAllByText("infrastructure").length).toBe(2)
    expect(within(grouped).getAllByText("docs").length).toBe(1)
    expect(grouped.querySelectorAll(".directory-row-group-danger").length).toBe(3)
    expect(within(grouped).queryByText("flagged")).toBeNull()
  })

  it("combines groups and flags in the third instance", () => {
    renderPage()

    const combined = rowsIn(2)

    expect(within(combined).getAllByText("flagged").length).toBe(2)
    const engine = within(combined).getByText("engine.ts").closest("button")
    expect(engine?.className).toContain("directory-row-group-danger")
    expect(within(combined).getByText("engine.ts").closest("button")?.textContent).toContain("flagged")
    const settlement = within(combined).getByText("settlement.ts").closest("button")
    expect(settlement?.className).toContain("directory-row-group-danger")
    expect(settlement?.textContent).not.toContain("flagged")
  })

  it("shows flagged without any group in the fourth instance", () => {
    renderPage()

    const flaggedOnly = rowsIn(3)

    expect(within(flaggedOnly).getAllByText("flagged").length).toBe(2)
    expect(flaggedOnly.querySelectorAll(".directory-tag").length).toBe(2)
    expect(flaggedOnly.querySelectorAll("[class*='directory-row-group-']").length).toBe(0)
    expect(within(flaggedOnly).getByText("engine.ts").closest("button")?.className).toContain("directory-row-flagged")
    expect(within(flaggedOnly).getByText("settlement.ts").closest("button")?.className).not.toContain("directory-row-flagged")
  })

  it("reloads the directory showing the spinner and the new entry", async () => {
    renderPage()

    const reload = rowsIn(4)

    expect(within(card(4)).queryByText("Reloading the directory (revision 0)")).toBeDefined()
    expect(within(reload).queryByText("generated-1.ts")).toBeNull()

    await userEvent.click(within(card(4)).getByRole("button", { name: "Refresh" }))

    expect(await within(card(4)).findByText("Reloading the directory (revision 1)")).toBeDefined()
    expect(within(reload).getByText("generated-1.ts")).toBeDefined()
    expect(within(reload).getAllByText("flagged").length).toBe(2)
  })

  it("keeps selection independent per instance", async () => {
    renderPage()

    await userEvent.click(within(rowsIn(0)).getByText("README.md"))

    expect(selectedNamesIn(0).join()).toContain("README.md")
    expect(selectedNamesIn(2).join()).toContain("engine.ts")
    expect(selectedNamesIn(3).join()).toContain("engine.ts")
  })
})
