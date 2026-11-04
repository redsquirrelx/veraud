import { afterEach, expect, it, vi } from "vitest"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { initializeI18n } from "../../shared/i18n/index.ts"
import { AuditEvidencePreview } from "./AuditEvidencePreview.tsx"

afterEach(async () => { vi.restoreAllMocks(); await initializeI18n("en") })

it("selects file, symbol and fragment examples in a read-only highlighted viewer without requests", async () => {
  const fetch = vi.spyOn(globalThis, "fetch")
  const { container } = render(<AuditEvidencePreview />)
  expect(screen.getByRole("note")).toHaveTextContent("not audit records")
  const list = within(screen.getByRole("list", { name: "Example evidences" }))
  const choices = list.getAllByRole("button")
  expect(choices).toHaveLength(3)
  expect(choices[0]).toHaveAttribute("aria-pressed", "true")
  expect(list.getByText("File")).toBeVisible()
  expect(list.getByText("Symbol")).toBeVisible()
  expect(list.getByText("Code fragment")).toBeVisible()
  expect(list.getByText("Lines 8–10")).toBeVisible()

  await userEvent.click(choices[1])
  const viewer = screen.getByRole("region", { name: "Read-only code viewer" })
  expect(within(viewer).getByText("example/src/controllers/ProjectController.ts")).toBeVisible()
  expect(Array.from(viewer.querySelectorAll(".ui-code-number"), (item) => item.textContent))
    .toEqual(Array.from({ length: 15 }, (_, index) => String(index + 1)))
  expect(Array.from(viewer.querySelectorAll(".ui-code-line-info .ui-code-number"), (item) => item.textContent)).toEqual(["8", "9", "10"])
  expect(viewer.querySelectorAll(".ui-code-line")[0]).not.toHaveClass("ui-code-line-info")
  expect(viewer.querySelectorAll(".ui-code-line")[14]).not.toHaveClass("ui-code-line-info")
  expect(viewer.querySelector(".hljs-keyword")).not.toBeNull()
  expect(within(viewer).getByText("Read-only")).toBeVisible()
  expect(screen.queryByRole("textbox")).toBeNull()
  expect(container.querySelector("[contenteditable=true]")).toBeNull()

  await userEvent.click(choices[2])
  expect(choices[1]).toHaveAttribute("aria-pressed", "false")
  expect(choices[2]).toHaveAttribute("aria-pressed", "true")
  expect(within(viewer).getByText("example/src/application/container.ts")).toBeVisible()
  expect(Array.from(viewer.querySelectorAll(".ui-code-number"), (item) => item.textContent))
    .toEqual(Array.from({ length: 15 }, (_, index) => String(index + 1)))
  expect(Array.from(viewer.querySelectorAll(".ui-code-line-info .ui-code-number"), (item) => item.textContent)).toEqual(["9", "10", "11"])
  expect(fetch).not.toHaveBeenCalled()
})

it("supports keyboard selection and translates the mockup into Spanish", async () => {
  await initializeI18n("es")
  render(<AuditEvidencePreview />)
  expect(screen.getByRole("heading", { name: "Maqueta del visor de evidencias" })).toBeVisible()
  const choices = within(screen.getByRole("list", { name: "Evidencias de ejemplo" })).getAllByRole("button")
  choices[1].focus()
  await userEvent.keyboard("{Enter}")
  expect(choices[1]).toHaveAttribute("aria-pressed", "true")
  expect(screen.getByRole("region", { name: "Visor de código de solo lectura" })).toBeVisible()
})
