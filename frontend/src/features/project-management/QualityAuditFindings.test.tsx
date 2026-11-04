import { afterEach, describe, expect, it } from "vitest"
import { cleanup, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { changeLanguage } from "../../shared/i18n/index.ts"
import { QualityAuditFindings } from "./QualityAuditFindings.tsx"

afterEach(async () => { cleanup(); await changeLanguage("en") })
const finding = (id: string, attribute: string, severity: string | null = "high") => ({
  id, title: `Finding ${id}`, description: `Description ${id}`, quality_attribute: attribute, severity,
  components: ["api", "database"], source_refs: [
    { record_type: "finding", record_id: id, agent_id: "detector" },
    { record_type: "finding", record_id: id, agent_id: "detector" },
    { record_type: "assessment", record_id: "review-1", agent_id: "reviewer" },
    { record_type: "finding", record_id: "another-finding", agent_id: "another-detector" },
  ],
})
const renderDetails = () => <p>Full original finding</p>

describe("audit findings list", () => {
  it("groups findings and shows their description, severity, components and original detecting agent", async () => {
    render(<QualityAuditFindings findings={[
      { ...finding("M1", "maintainability"), subcharacteristic: "modularity", verification_status: "verified",
        impact: "Changes propagate across modules.", recommendation: "Separate the responsibilities." }, finding("S1", "security", "critical"),
      finding("P1", "performance_efficiency", "info"), finding("M2", "maintainability", "low"),
    ]} renderDetails={renderDetails} />)
    expect(screen.getAllByRole("heading", { level: 4 }).map((heading) => heading.textContent)).toEqual([
      "Security (1)", "Maintainability (2)", "Performance (1)",
    ])
    const item = within(screen.getByRole("heading", { name: "Finding M1" }).closest("li")!)
    expect(item.getByText("Description M1")).toBeInTheDocument()
    expect(item.getByText("Severity: High")).toBeInTheDocument()
    expect(item.getByText("Attribute: Maintainability").closest(".ui-badge")).toBeInTheDocument()
    expect(item.getByText("Subcharacteristic: Modularity").closest(".ui-badge")).toBeInTheDocument()
    expect(item.getByText("Validation: Verified").closest(".ui-badge")).toHaveClass("ui-badge-success")
    expect(item.queryByText("api, database")).not.toBeInTheDocument()
    expect(item.queryByText("detector")).not.toBeInTheDocument()
    expect(item.queryByText("Changes propagate across modules.")).not.toBeInTheDocument()
    expect(screen.queryByText("reviewer")).not.toBeInTheDocument()
    expect(screen.queryByText("another-detector")).not.toBeInTheDocument()
    expect(screen.queryByText("Full original finding")).not.toBeInTheDocument()
    const user = userEvent.setup()
    const trigger = item.getByRole("button", { name: "Finding M1" })
    trigger.focus()
    await user.keyboard("{Enter}")
    const drawer = within(await screen.findByRole("dialog", { name: "Finding M1" }))
    expect(drawer.getByText("M1")).toBeInTheDocument()
    expect(drawer.getByText("Description M1")).toBeInTheDocument()
    expect(drawer.getByText("Changes propagate across modules.")).toBeInTheDocument()
    expect(drawer.getByText("Separate the responsibilities.")).toBeInTheDocument()
    expect(drawer.getByText("api, database")).toBeInTheDocument()
    expect(drawer.getByText("detector")).toBeInTheDocument()
    expect(drawer.queryByText("reviewer")).not.toBeInTheDocument()
    expect(drawer.queryByText("another-detector")).not.toBeInTheDocument()
    await user.click(drawer.getByText("View original details"))
    expect(await drawer.findByText("Full original finding")).toBeInTheDocument()
    await changeLanguage("es")
    expect(screen.getByText("Mantenibilidad (2)")).toBeInTheDocument()
    expect(item.getByText("Severidad: Alta")).toBeInTheDocument()
    expect(drawer.getByText("Agente detector")).toBeInTheDocument()
    expect(drawer.getByText("Impacto sobre el software")).toBeInTheDocument()
    expect(drawer.getByText("Recomendaciones")).toBeInTheDocument()
    expect(item.getByText("Atributo: Mantenibilidad")).toBeInTheDocument()
    expect(item.getByText("Subcaracterística: Modularidad")).toBeInTheDocument()
    expect(item.getByText("Validación: Verificado")).toBeInTheDocument()
    await user.keyboard("{Escape}")
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    await waitFor(() => expect(trigger).toHaveFocus())
    await user.click(screen.getByRole("button", { name: "Finding S1" }))
    const nextDrawer = within(await screen.findByRole("dialog", { name: "Finding S1" }))
    expect(nextDrawer.getByText("S1")).toBeInTheDocument()
    expect(nextDrawer.queryByText("Changes propagate across modules.")).not.toBeInTheDocument()
    expect(nextDrawer.queryByText("Full original finding")).not.toBeInTheDocument()
  })

  it("does not invent missing provenance, components or severity", async () => {
    render(<QualityAuditFindings findings={[{ id: "legacy", title: "Legacy finding", quality_attribute: "custom_attribute" }]}
      renderDetails={renderDetails} />)
    expect(screen.getByRole("heading", { name: "custom attribute (1)" })).toBeInTheDocument()
    expect(screen.getByText("Severity: Not recorded")).toBeInTheDocument()
    expect(screen.getAllByText("Not recorded")).toHaveLength(1)
    expect(screen.getByText("Attribute: custom attribute")).toBeInTheDocument()
    expect(screen.getByText("Subcharacteristic: Not recorded")).toBeInTheDocument()
    expect(screen.getByText("Validation: Not recorded")).toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "Legacy finding" }))
    const drawer = within(await screen.findByRole("dialog", { name: "Legacy finding" }))
    for (const label of ["Full description", "Software impact", "Recommendations", "Affected component", "Detecting agent"]) {
      expect(drawer.getByText(label).closest("div")).toHaveTextContent(`${label}Not recorded`)
    }
  })

  it.each([
    ["inconclusive", "Inconclusive", "warning"], ["discarded", "Discarded", "neutral"], ["pending_review", "pending review", "neutral"],
  ])("preserves the reported %s validation status without marking it verified", (status, label, tone) => {
    render(<QualityAuditFindings findings={[{ ...finding("S1", "security"), subcharacteristic: "custom_dimension", verification_status: status }]}
      renderDetails={renderDetails} />)
    expect(screen.getByText(`Validation: ${label}`).closest(".ui-badge")).toHaveClass(`ui-badge-${tone}`)
    expect(screen.getByText("Subcharacteristic: custom dimension")).toBeInTheDocument()
    expect(screen.queryByText("Validation: Verified")).not.toBeInTheDocument()
  })

  it("sorts globally by severity and paginates ten findings at a time without modifying the original order", async () => {
    const findings = Object.freeze([
      ...Array.from({ length: 18 }, (_, index) => finding(`L${index + 1}`, "maintainability", "low")),
      finding("I1", "security", "info"), finding("C1", "maintainability", "critical"),
      finding("H1", "security", "high"), finding("M1", "maintainability", "medium"), finding("U1", "security", null),
    ])
    const originalIds = findings.map((item) => item.id)
    const { rerender } = render(<QualityAuditFindings findings={findings} renderDetails={renderDetails} />)
    const titles = () => screen.getAllByRole("heading", { level: 5 }).map((heading) => heading.textContent)
    expect(titles()).toEqual(["Finding C1", "Finding H1", "Finding M1", ...Array.from({ length: 7 }, (_, index) => `Finding L${index + 1}`)])
    expect(screen.getByRole("status")).toHaveTextContent("Findings 1–10 of 23")
    expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled()
    const user = userEvent.setup()
    await user.click(screen.getByRole("button", { name: "Next page" }))
    expect(titles()).toEqual(Array.from({ length: 10 }, (_, index) => `Finding L${index + 8}`))
    expect(screen.getByRole("status")).toHaveTextContent("Findings 11–20 of 23")
    await user.click(screen.getByRole("button", { name: "Next page" }))
    expect(titles()).toEqual(["Finding L18", "Finding I1", "Finding U1"])
    expect(screen.getByRole("status")).toHaveTextContent("Findings 21–23 of 23")
    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled()
    await user.click(screen.getByRole("button", { name: "Finding L18" }))
    expect(within(await screen.findByRole("dialog", { name: "Finding L18" })).getByText("L18")).toBeInTheDocument()
    await user.keyboard("{Escape}")
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
    await user.click(screen.getByRole("button", { name: "Previous page" }))
    expect(titles()).toHaveLength(10)
    expect(screen.getByText("Page 2 of 3")).toBeInTheDocument()
    expect(findings.map((item) => item.id)).toEqual(originalIds)
    rerender(<QualityAuditFindings findings={[finding("NEW", "security")]} renderDetails={renderDetails} />)
    expect(titles()).toEqual(["Finding NEW"])
    expect(screen.getByRole("status")).toHaveTextContent("Findings 1–1 of 1")
    expect(screen.queryByRole("button", { name: "Next page" })).not.toBeInTheDocument()
  })

  it("allows 10, 20 or 50 findings per page and resets the current page when the size changes", async () => {
    render(<QualityAuditFindings findings={Array.from({ length: 51 }, (_, index) => finding(`M${index + 1}`, "maintainability"))}
      renderDetails={renderDetails} />)
    const user = userEvent.setup()
    const size = screen.getByRole("combobox", { name: "Findings per page" })
    expect(size).toHaveValue("10")
    expect(within(size).getAllByRole("option").map((option) => option.getAttribute("value"))).toEqual(["10", "20", "50"])
    await user.click(screen.getByRole("button", { name: "Next page" }))
    await user.selectOptions(size, "20")
    expect(screen.getAllByRole("heading", { level: 5 })).toHaveLength(20)
    expect(screen.getByRole("status")).toHaveTextContent("Findings 1–20 of 51")
    expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled()
    await user.click(screen.getByRole("button", { name: "Next page" }))
    expect(screen.getByRole("status")).toHaveTextContent("Findings 21–40 of 51")
    await user.selectOptions(size, "50")
    expect(screen.getAllByRole("heading", { level: 5 })).toHaveLength(50)
    expect(screen.getByRole("status")).toHaveTextContent("Findings 1–50 of 51")
    await user.click(screen.getByRole("button", { name: "Next page" }))
    expect(screen.getAllByRole("heading", { level: 5 })).toHaveLength(1)
    expect(screen.getByRole("heading", { name: "Finding M51" })).toBeInTheDocument()
    await user.selectOptions(size, "10")
    expect(screen.getAllByRole("heading", { level: 5 })).toHaveLength(10)
    expect(screen.getByRole("status")).toHaveTextContent("Findings 1–10 of 51")
  })

  it("allows ascending or descending severity, keeps unknown values last and resets the page on sort changes", async () => {
    render(<QualityAuditFindings findings={[
      ...Array.from({ length: 11 }, (_, index) => finding(`H${index + 1}`, "maintainability", "high")),
      finding("I1", "security", "info"), finding("L1", "security", "low"), finding("M1", "security", "medium"),
      finding("C1", "security", "critical"), finding("U1", "security", null), finding("U2", "security", "future_severity"),
    ]} renderDetails={renderDetails} />)
    const user = userEvent.setup()
    const order = screen.getByRole("combobox", { name: "Severity order" })
    const titles = () => screen.getAllByRole("heading", { level: 5 }).map((heading) => heading.textContent)
    expect(order).toHaveValue("descending")
    await user.click(screen.getByRole("button", { name: "Next page" }))
    await user.selectOptions(order, "ascending")
    expect(titles()).toEqual(["Finding I1", "Finding L1", "Finding M1", ...Array.from({ length: 7 }, (_, index) => `Finding H${index + 1}`)])
    expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled()
    expect(screen.getByRole("status")).toHaveTextContent("Lowest to highest severity")
    await user.click(screen.getByRole("button", { name: "Next page" }))
    expect(titles().slice(-3)).toEqual(["Finding C1", "Finding U1", "Finding U2"])
    await user.selectOptions(order, "descending")
    expect(titles()[0]).toBe("Finding C1")
    expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled()
    await user.selectOptions(screen.getByRole("combobox", { name: "Findings per page" }), "50")
    expect(titles().slice(-2)).toEqual(["Finding U1", "Finding U2"])
    await changeLanguage("es")
    expect(screen.getByRole("combobox", { name: "Hallazgos por página" })).toHaveValue("50")
    expect(screen.getByRole("combobox", { name: "Orden de severidad" })).toHaveValue("descending")
  })

  it("distinguishes an empty list from missing report data", () => {
    const { rerender } = render(<QualityAuditFindings findings={[]} renderDetails={renderDetails} />)
    expect(screen.getByText("No findings were identified in this audit")).toBeInTheDocument()
    rerender(<QualityAuditFindings findings={null} renderDetails={renderDetails} />)
    expect(screen.getByText("Not recorded")).toBeInTheDocument()
    expect(screen.queryByText("No findings were identified in this audit")).not.toBeInTheDocument()
  })
})
